from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

import pandas as pd

from base import DegradedDataError, DegradedScheduleError
from context import OrderIntent, PhaseContext
from engine import StrategyEngine
from symbol_key import canonical_symbol_key
from shared_oracle_helpers import score_symbol_native
from cost_model import wire_cost_models
from tag_schema import encode_entry_tag
from indicators import INDICATOR_KEYS, TBounceTracker, weekly_aggregate
from universe_select import (
    DvWindow,
    apply_floors,
    rank_and_cap,
    rolling_dv_mean,
    update_dv_windows,
)


def coarse_to_dollar_volume(coarse: Iterable[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for c in coarse:
        ticker = str(c.symbol.value).lower()
        dv = float(c.dollar_volume)
        if not math.isfinite(dv):
            raise DegradedDataError(
                f"non-finite coarse dollar_volume: ticker={ticker!r} dollar_volume={dv!r}; "
                f"degraded data must fail loud, never enter the rolling-DV window (#261-2)"
            )
        out[ticker] = dv
    return out


def coarse_to_close(coarse: Iterable[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for c in coarse:
        ticker = str(c.symbol.value).lower()
        price = float(c.price)
        if not math.isfinite(price):
            raise DegradedDataError(
                f"non-finite coarse price (close): ticker={ticker!r} price={price!r}; "
                f"degraded data must fail loud, never feed the price floor (#261-2)"
            )
        out[ticker] = price
    return out


FUNNEL_DAILY_STAGES: tuple[str, ...] = ("signal_winners", "regime_pass", "regime_blocked_days")
FUNNEL_INTRADAY_STAGES: tuple[str, ...] = (
    "preflight_pass", "gap_eligible", "confirm_fire", "injection_survives", "sized", "cash_ok",
)
FUNNEL_FIRE_STAGES: tuple[str, ...] = ("orders",)
FUNNEL_STAGES: tuple[str, ...] = (
    FUNNEL_DAILY_STAGES + FUNNEL_INTRADAY_STAGES + FUNNEL_FIRE_STAGES
)

FUNNEL_DISTINCT_STAGES: tuple[str, ...] = ("preflight_pass", "injection_survives")
FUNNEL_CANDIDATE_DAY_STAGES: tuple[str, ...] = tuple(
    s for s in FUNNEL_INTRADAY_STAGES if s not in FUNNEL_DISTINCT_STAGES
)
FUNNEL_STAGE_SEMANTICS: dict[str, str] = {
    "signal_winners": "daily",
    "regime_pass": "daily",
    "regime_blocked_days": "daily",
    "preflight_pass": "distinct",
    "gap_eligible": "candidate_days",
    "confirm_fire": "candidate_days",
    "injection_survives": "distinct",
    "sized": "candidate_days",
    "cash_ok": "candidate_days",
    "orders": "fire",
}


def active_set_hash(symbols: Iterable[str]) -> tuple[int, str]:
    syms = sorted(symbols)
    h = sha256(",".join(syms).encode("utf-8")).hexdigest()
    return len(syms), h


try:
    from AlgorithmImports import (
        Calendar,
        DataNormalizationMode,
        Field,
        IchimokuKinkoHyo,
        Market,
        MovingAverageType,
        OrderStatus,
        QCAlgorithm,
        Resolution,
        RollingWindow,
        SecurityType,
        Symbol,
        TradeBar,
        TradeBarConsolidator,
    )
except ImportError:
    QCAlgorithm = object
    DataNormalizationMode = Resolution = SecurityType = Market = Symbol = None
    Calendar = IchimokuKinkoHyo = RollingWindow = TradeBar = TradeBarConsolidator = None
    Field = MovingAverageType = OrderStatus = None


def _to_decimal(x: Any) -> Decimal:
    xf = float(x)
    if not math.isfinite(xf):
        return Decimal("0")
    return Decimal(str(xf))


def _make_trade_bar(
    time: Any, symbol: Any, open_: float, high: float, low: float, close: float,
    volume: float, period: Any,
) -> Any:
    bar = TradeBar()
    bar.symbol = symbol
    bar.time = time
    bar.period = period
    bar.open = _to_decimal(open_)
    bar.high = _to_decimal(high)
    bar.low = _to_decimal(low)
    bar.close = _to_decimal(close)
    bar.volume = _to_decimal(volume)
    return bar


class BctEngineAlgorithm(QCAlgorithm):

    STRATEGY_CONFIG: Any = None
    START_DATE: tuple[int, int, int] = (2025, 1, 1)
    END_DATE: tuple[int, int, int] = (2025, 12, 31)
    CASH: int = 100_000

    PREFILTER_DV: float = 25_000_000.0
    MIN_PRICE: float = 10.0
    MIN_AVG_DOLLAR_VOLUME: float = 100_000_000.0
    COARSE_MAX: int = 9999
    ADV_WINDOW: int = 20

    BROKEN_ZERO_MIN_FEED: int = 100

    WARMUP_DAYS: int = 560
    CONTINUOUS_WEEKLY: bool = False
    AFTER_CLOSE_MIN: int = 10

    INTRADAY_SUBSCRIBE_CAP: int = 50
    INTRADAY_TENKAN: int = 9
    INTRADAY_VOL_WINDOW: int = 20

    SLIPPAGE_PERCENT: float = 0.0005

    ENTRY_TAG_MAX: int = 200

    def initialize(self) -> None:
        self.set_start_date(*self.START_DATE)
        self.set_end_date(*self.END_DATE)
        self.set_cash(self.CASH)
        self.set_benchmark("SPY")
        self.set_time_zone("America/New_York")
        self.set_warmup(timedelta(days=self.WARMUP_DAYS))
        if self.CONTINUOUS_WEEKLY:
            self._warmup_cache: dict[str, dict] = {}

        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW

        self.spy = self.add_equity("SPY", Resolution.DAILY)
        self.spy.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.spy_sma200 = self.sma("SPY", 200)
        self.vix = self.add_index("VIX", Resolution.DAILY).symbol
        self.vix_ichi = self.ichimoku(self.vix, 9, 26, 26, 52, 26, 26)

        self._active: set[Any] = set()
        self._indicators: dict[Any, dict[str, Any]] = {}
        self._position_meta: dict[Any, Any] = {}

        self._intraday: dict[Any, dict[str, Any]] = {}
        self._intraday_active: set[Any] = set()

        self._candidate_snapshot: dict[Any, dict[str, Any]] = {}
        self._last_daily_date: Any = None
        self._entry_confirm: dict[Any, Any] = {}
        self._pending_entry_today: set[Any] = set()
        self._entered_today: set[Any] = set()

        self._funnel_cum: dict[str, int] = {stage: 0 for stage in FUNNEL_STAGES}
        self._funnel_today: dict[str, set[Any]] = {stage: set() for stage in FUNNEL_INTRADAY_STAGES}
        self._funnel_seen: dict[str, set[Any]] = {stage: set() for stage in FUNNEL_DISTINCT_STAGES}

        self._sched_trading_days: int = 0
        self._sched_decisions: int = 0

        self._ranked_today: list[str] = []
        self._trailing_dv: dict[str, float] = {}
        self._bar_metrics: dict[str, tuple[float, float]] = {}

        self._dv_windows: dict[str, DvWindow] = {}
        self._dv_day_index: int = -1

        self.add_universe(self._coarse_selection)

        self.schedule.on(
            self.date_rules.every_day(self.spy.symbol),
            self.time_rules.after_market_close(self.spy.symbol, self.AFTER_CLOSE_MIN),
            self._on_after_close_decision,
        )
        self._schedule_armed = True

        wire_cost_models(self, slippage_percent=self.SLIPPAGE_PERCENT)

        self.engine = StrategyEngine(config=self.STRATEGY_CONFIG, qc=self)

        self.log(
            f"LEAN_ENTRY_INIT|live_coarse_selectiongate|prefilter_dv={self.PREFILTER_DV}|"
            f"min_price={self.MIN_PRICE}|min_avg_dv={self.MIN_AVG_DOLLAR_VOLUME}|"
            f"coarse_max={self.COARSE_MAX}|adv_window={self.ADV_WINDOW}|"
            f"start={self.START_DATE}|end={self.END_DATE} "
            f"(prefilter -> floors -> rank+cap at selection; subscribe only qualifying)"
        )

    def _coarse_selection(self, coarse: Any) -> Any:
        date_str = self.time.strftime("%Y-%m-%d")
        coarse_dv = coarse_to_dollar_volume(coarse)
        coarse_close = coarse_to_close(coarse)

        n_in = len(coarse_dv)
        if n_in == 0:
            raise DegradedDataError(
                f"empty coarse feed on a trading day: date={date_str} (QC fired the coarse "
                f"selection callback — a real session — but 0 names arrived). A missing/empty "
                f"feed on a known trading day is a DATA GAP that must fail loud, never read as a "
                f"silent holiday/empty universe (the #173 empty-warmup mirage) (#261-5)"
            )

        self._dv_day_index += 1
        update_dv_windows(
            self._dv_windows, coarse_dv, day_index=self._dv_day_index, maxlen=self.ADV_WINDOW,
        )

        bar_metrics: dict[str, tuple[float, float]] = {}
        for ticker, sdv in coarse_dv.items():
            if sdv < self.PREFILTER_DV:
                continue
            window = self._dv_windows[ticker].dv
            close = coarse_close.get(ticker)
            if close is None:
                continue
            bar_metrics[ticker] = (close, rolling_dv_mean(window))

        eligible = apply_floors(
            bar_metrics, min_price=self.MIN_PRICE,
            min_avg_dollar_volume=self.MIN_AVG_DOLLAR_VOLUME,
        )
        dv_by_ticker = {t: bar_metrics[t][1] for t in eligible}
        ranked = rank_and_cap(eligible, dv_by_ticker, coarse_max=self.COARSE_MAX)

        if not ranked and n_in >= self.BROKEN_ZERO_MIN_FEED:
            raise DegradedDataError(
                f"broken-0 selection on a populated coarse feed: date={date_str} "
                f"names_in={n_in} eligible={len(eligible)} ranked=0 — a full feed collapsed to "
                f"an EMPTY universe (degraded data: DV/price column corrupted, every name below "
                f"the floor?). A non-empty feed yielding zero selection must fail loud, never a "
                f"silent empty universe (the −0.616 empty-universe mirage) (#261-6)"
            )

        self._ranked_today = ranked
        self._trailing_dv = {t: bar_metrics[t][1] for t in ranked if t in bar_metrics}
        self._bar_metrics = bar_metrics

        count, h = active_set_hash(ranked)
        self.log(f"ACTIVE_SET|{date_str}|count={count}|hash={h}")
        if getattr(self, "_schedule_armed", False) and not getattr(self, "is_warming_up", False):
            self._sched_trading_days = getattr(self, "_sched_trading_days", 0) + 1
            self._assert_schedule_health()
        self._ranked_today = ranked
        return [Symbol.create(t.upper(), SecurityType.EQUITY, Market.USA) for t in ranked]

    def on_securities_changed(self, changes: Any) -> None:
        for s in changes.added_securities:
            sym = s.symbol
            self._active.add(sym)
            if sym not in self._indicators:
                self._register_indicators(sym)
        for s in changes.removed_securities:
            sym = s.symbol
            self._active.discard(sym)
            if sym in self._indicators:
                self.subscription_manager.remove_consolidator(
                    sym, self._indicators[sym]["consolidator"]
                )
                self.subscription_manager.remove_consolidator(
                    sym, self._indicators[sym]["daily_consolidator"]
                )
                del self._indicators[sym]

    def _register_indicators(self, sym: Any) -> None:
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)
        adx = self.adx(sym, 9)
        adx_window = RollingWindow[float](5)
        adx.updated += lambda _s, _pt: adx_window.add(adx.current.value)
        roc13 = self.roc(sym, 13)
        macd = self.macd(sym, 12, 26, 9, MovingAverageType.EXPONENTIAL, Resolution.DAILY)
        macd_hist_window = RollingWindow[float](2)
        macd.updated += lambda _s, _pt: macd_hist_window.add(macd.histogram.current.value)
        vol_sma20 = self.sma(sym, 20, Resolution.DAILY, Field.VOLUME)
        tbounce = TBounceTracker()
        w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
        w_close = RollingWindow[float](28)
        consolidator = TradeBarConsolidator(Calendar.WEEKLY)

        def _on_weekly(_: Any, bar: TradeBar) -> None:
            w_ichi.update(bar)
            w_close.add(bar.close)

        consolidator.data_consolidated += _on_weekly
        self.subscription_manager.add_consolidator(sym, consolidator)

        daily_consolidator = TradeBarConsolidator(timedelta(days=1))

        def _on_daily(_: Any, bar: TradeBar) -> None:
            t = d_ichi.tenkan.current.value if d_ichi.is_ready else 0.0
            tbounce.update(
                float(bar.open), float(bar.high), float(bar.low), float(bar.close), float(t)
            )

        daily_consolidator.data_consolidated += _on_daily
        self.subscription_manager.add_consolidator(sym, daily_consolidator)

        if not self.is_warming_up:
            self._seed_weekly(sym, w_ichi, w_close)
            self._seed_daily(
                sym, d_ichi, sma200, adx, adx_window, roc13, macd, vol_sma20, tbounce
            )

        self._indicators[sym] = {
            "d_ichi": d_ichi,
            "w_ichi": w_ichi,
            "w_close": w_close,
            "sma200": sma200,
            "adx": adx,
            "adx_window": adx_window,
            "roc13": roc13,
            "consolidator": consolidator,
            "macd": macd,
            "macd_hist_window": macd_hist_window,
            "vol_sma20": vol_sma20,
            "tbounce": tbounce,
            "daily_consolidator": daily_consolidator,
        }
        assert set(self._indicators[sym]) == set(INDICATOR_KEYS)

    def _subscribe_intraday(self, sym: Any) -> None:
        if sym in self._intraday:
            return
        eq = self.add_equity(sym.value, Resolution.MINUTE)
        eq.set_data_normalization_mode(DataNormalizationMode.RAW)
        intraday_tenkan = IchimokuKinkoHyo(
            self.INTRADAY_TENKAN, 26, 26, 52, 26, 26
        )
        vol_window = RollingWindow[float](self.INTRADAY_VOL_WINDOW)
        self._intraday[sym] = {
            "intraday_tenkan": intraday_tenkan,
            "vol_window": vol_window,
            "last_close": None,
            "last_bar": None,
        }
        self._intraday_active.add(sym)
        if not self.is_warming_up:
            self._seed_intraday(sym, intraday_tenkan, vol_window)
        self.log(f"INTRADAY_SUBSCRIBE|{sym.value}|n_active={len(self._intraday_active)}")

    def _seed_intraday(self, sym: Any, intraday_tenkan: Any, vol_window: Any) -> None:
        today = self.time.date()
        for bar in self.history[TradeBar](sym, 8 * 78, Resolution.MINUTE):
            if bar.end_time.date() >= today:
                continue
            intraday_tenkan.update(bar)
            vol_window.add(float(bar.volume))

    def _unsubscribe_intraday(self, sym: Any) -> None:
        if sym not in self._intraday:
            return
        if self.portfolio[sym].invested:
            return
        del self._intraday[sym]
        self._intraday_active.discard(sym)
        self.remove_security(sym)
        self.log(f"INTRADAY_UNSUBSCRIBE|{sym.value}|n_active={len(self._intraday_active)}")

    def _sync_intraday_subscriptions(self, candidates: list[str]) -> None:
        active_by_key = {canonical_symbol_key(s): s for s in self._active}
        capped = candidates[: self.INTRADAY_SUBSCRIBE_CAP]
        if len(candidates) > self.INTRADAY_SUBSCRIBE_CAP:
            self.log(
                f"INTRADAY_CAP|candidates={len(candidates)}|capped_to={self.INTRADAY_SUBSCRIBE_CAP}"
            )
        want: set[Any] = set()
        for tk in capped:
            sym = active_by_key.get(canonical_symbol_key(tk))
            if sym is not None:
                want.add(sym)
        for sym in list(self._intraday_active):
            if self.portfolio[sym].invested:
                want.add(sym)
        for sym in want - self._intraday_active:
            self._subscribe_intraday(sym)
        for sym in self._intraday_active - want:
            self._unsubscribe_intraday(sym)

    def _seed_weekly(self, sym: Any, w_ichi: Any, w_close: Any) -> None:
        hist = self.history(sym, self.WARMUP_DAYS, Resolution.DAILY)
        if hist is None or hist.empty:
            return
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        for wb in weekly_aggregate(hist):
            monday = wb["friday"] - timedelta(days=4)
            bar = _make_trade_bar(
                monday, sym, wb["open"], wb["high"], wb["low"], wb["close"],
                wb["volume"], timedelta(weeks=1),
            )
            w_ichi.update(bar)
            w_close.add(float(wb["close"]))

    def _continuous_weekly_scalars(self, sym: Any) -> dict | None:
        from lean_indicators import WeeklyIchimokuAsOf
        ind = self._indicators.get(sym)
        if ind is None:
            return None
        d_ichi = ind["d_ichi"]; sma200 = ind["sma200"]; adx = ind["adx"]
        adx_window = ind["adx_window"]; roc13 = ind["roc13"]
        if not (d_ichi.is_ready and sma200.is_ready and adx.is_ready and roc13.is_ready):
            return None
        if adx_window.count < 4:
            return None
        hist = self.history(sym, self.WARMUP_DAYS, Resolution.DAILY)
        if hist is None or hist.empty:
            return None
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        w = WeeklyIchimokuAsOf()
        for ts, row in hist.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            w.update(d, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))
        if not w.is_ready:
            return None
        d_price = float(self.securities[sym].price)
        if d_price <= 0:
            return None
        return {
            "d_price": d_price,
            "d_tenkan": d_ichi.tenkan.current.value,
            "d_cloud_top": max(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value),
            "ma200": sma200.current.value,
            "w_tenkan": w.tenkan, "w_kijun": w.kijun,
            "w_senkou_a": w.senkou_a, "w_senkou_b": w.senkou_b,
            "w_close_0": w.w_close(0), "w_close_26": w.w_close(26),
            "adx_now": adx.current.value,
            "plus_di": adx.positive_directional_index.current.value,
            "minus_di": adx.negative_directional_index.current.value,
            "adx_3back": adx_window[3],
            "roc13": roc13.current.value,
        }

    def _seed_daily(
        self,
        sym: Any,
        d_ichi: Any,
        sma200: Any,
        adx: Any,
        adx_window: Any,
        roc13: Any,
        macd: Any,
        vol_sma20: Any,
        tbounce: Any,
    ) -> None:
        today = self.time.date()
        for bar in self.history[TradeBar](sym, self.WARMUP_DAYS, Resolution.DAILY):
            if bar.end_time.date() >= today:
                continue
            et = bar.end_time
            o, h, lo, c, v = (
                float(bar.open), float(bar.high), float(bar.low), float(bar.close),
                float(bar.volume),
            )
            d_ichi.update(bar)
            adx.update(bar)
            sma200.update(et, c)
            roc13.update(et, c)
            macd.update(et, c)
            vol_sma20.update(et, v)
            tk = d_ichi.tenkan.current.value if d_ichi.is_ready else 0.0
            tbounce.update(o, h, lo, c, float(tk))

    def on_data(self, data: Any) -> None:
        if self.is_warming_up:
            return

        bars = getattr(data, "bars", None)
        fed_intraday = False
        if bars is not None and self._intraday:
            for sym, st in self._intraday.items():
                bar = bars.get(sym) if hasattr(bars, "get") else None
                if bar is None:
                    continue
                st["intraday_tenkan"].update(bar)
                st["vol_window"].add(float(getattr(bar, "volume", 0.0)))
                st["last_close"] = float(bar.close)
                st["last_bar"] = bar
                fed_intraday = True
            if fed_intraday:
                ictx = PhaseContext(qc=self, time=self.time, data=data)
                ictx.clock = "intraday"
                self._inject_intraday_candidates(ictx)
                self.engine.on_intraday_bar(ictx)
                self._fold_intraday_funnel(ictx)


    def _on_after_close_decision(self) -> None:
        if self.is_warming_up:
            return
        today = self.time.date()
        if today == getattr(self, "_last_daily_date", None):
            return
        self._last_daily_date = today
        self._sched_decisions = getattr(self, "_sched_decisions", 0) + 1
        ctx = PhaseContext(qc=self, time=self.time, data=None)
        ctx.clock = "daily"
        if self.CONTINUOUS_WEEKLY:
            for sym in list(self._indicators):
                scalars = self._continuous_weekly_scalars(sym)
                if scalars is not None:
                    self._warmup_cache.setdefault(sym.value, {})[today] = scalars
        self.engine.on_data_with_ctx(ctx)
        signal_winner_tickers = [intent.ticker for intent in ctx.bar_state.sized_orders]
        blocked = bool(getattr(ctx.bar_state, "bar_blocked", False))
        self._accumulate_daily_funnel(signal_winner_tickers, blocked)
        if blocked:
            winners: list[str] = []
            log = getattr(self, "log", None)
            if callable(log):
                log(f"REGIME_GATE|{today}|blocked — zero intraday candidates captured (#277)")
        else:
            winners = signal_winner_tickers
        self._sync_intraday_subscriptions(winners)
        self._capture_candidate_snapshot(winners)

    def _assert_schedule_health(self) -> None:
        gap = getattr(self, "_sched_trading_days", 0) - getattr(self, "_sched_decisions", 0)
        if gap > 1:
            raise DegradedScheduleError(
                f"daily-decision UNDER-FIRE (#313 watchdog): {self._sched_trading_days} post-warmup "
                f"trading days but only {self._sched_decisions} daily decisions ran (gap {gap} > 1) — "
                f"the scheduled after-close event is not firing. The daily DECISION clock has gone "
                f"DARK; refusing to run blind."
            )

    def on_end_of_algorithm(self) -> None:
        self._process_eod_funnel()
        if not getattr(self, "_schedule_armed", False):
            return
        gap = getattr(self, "_sched_trading_days", 0) - getattr(self, "_sched_decisions", 0)
        if gap > 1:
            raise DegradedScheduleError(
                f"daily-decision UNDER-FIRE at end-of-run (#313 watchdog backstop): "
                f"{self._sched_trading_days} post-warmup trading days vs {self._sched_decisions} "
                f"decisions (gap {gap} > 1) — the scheduled after-close trigger under-fired."
            )

    def _signal_min_score(self) -> int:
        try:
            slot = self.engine.config.phases.get("signal")
            if isinstance(slot, list):
                slot = slot[0]
            return int(getattr(slot.params, "min_score", 7))
        except Exception:
            return 7

    def _build_entry_tag(self, sym: Any) -> str:
        snap = getattr(self, "_candidate_snapshot", {}).get(sym, {})
        ist = getattr(self, "_intraday", {}).get(sym, {})
        sp = snap.get("signal_price")
        last_close = ist.get("last_close")
        gap = (last_close - sp) / sp if (sp and last_close is not None) else None
        vol = None
        vw = ist.get("vol_window")
        last_bar = ist.get("last_bar")
        n = getattr(vw, "count", 0) if vw is not None else 0
        if n > 0 and last_bar is not None:
            mean_vol = sum(vw[i] for i in range(n)) / n
            if mean_vol > 0:
                vol = float(last_bar.volume) / mean_vol
        tk = ist.get("intraday_tenkan")
        tdist = ((last_close - float(tk.current.value)) / last_close
                 if (tk is not None and getattr(tk, "is_ready", False) and last_close) else None)
        val = getattr(sym, "value", None)
        ranked = getattr(self, "_ranked_today", [])
        ranked_key_to_rank: dict[str, int] = {}
        for i, t in enumerate(ranked):
            ranked_key_to_rank.setdefault(canonical_symbol_key(t), i)
        rank = ranked_key_to_rank.get(canonical_symbol_key(sym)) if val is not None else None
        tag = encode_entry_tag(score=snap.get("score"), conditions=(snap.get("conditions") or None),
                               gap=gap, vol=vol, tdist=tdist, rank=rank)
        if len(tag) > self.ENTRY_TAG_MAX:
            raise DegradedDataError(
                f"entry tag {len(tag)} > ENTRY_TAG_MAX={self.ENTRY_TAG_MAX} for {val} — would "
                f"truncate the learn-substrate context; fail loud (#archive B2, never silent-truncate)"
            )
        return tag

    def _capture_candidate_snapshot(self, winners: "list[str]") -> None:
        active_by_key = {canonical_symbol_key(s): s for s in getattr(self, "_active", set())}
        indicators = getattr(self, "_indicators", {})
        decision_date = self.time.date()
        snap: dict[Any, dict[str, Any]] = {}
        for ticker in winners:
            sym = active_by_key.get(canonical_symbol_key(ticker))
            if sym is None:
                continue
            ind = indicators.get(sym)
            d_ichi = ind.get("d_ichi") if ind else None
            if d_ichi is None or not getattr(d_ichi, "is_ready", False):
                continue
            try:
                scored = score_symbol_native(self, sym, ind)
            except Exception as exc:
                scored = None
                _log = getattr(self, "log", None)
                if callable(_log):
                    _log(f"CONTEXT_GAP|{decision_date}|{getattr(sym, 'value', sym)}|rescore-failed:{type(exc).__name__}")
            min_score = self._signal_min_score()
            if scored is not None and int(scored["score"]) < min_score:
                _log = getattr(self, "log", None)
                if callable(_log):
                    _log(f"CONTEXT_GAP|{decision_date}|{getattr(sym, 'value', sym)}|score-drift:"
                         f"rescore={scored['score']}<min_score={min_score} — booleans suspect, dropped")
                scored = None
            conditions = [bool(c) for c in scored["conditions"]] if scored else []
            snap[sym] = {
                "signal_price": float(self.securities[sym].price),
                "daily_kijun": float(d_ichi.kijun.current.value),
                "daily_cloud_bottom": float(min(d_ichi.senkou_a.current.value,
                                                d_ichi.senkou_b.current.value)),
                "decision_date": decision_date,
                "score": int(scored["score"]) if scored else None,
                "conditions": conditions,
            }
        self._candidate_snapshot = snap
        log = getattr(self, "log", None)
        if callable(log):
            log(f"SNAPSHOT|{decision_date}|candidates={len(snap)}")

    def snapshot_for_entry(self, sym: Any) -> "dict[str, Any] | None":
        snap = self._candidate_snapshot.get(sym)
        if snap is None:
            log = getattr(self, "log", None)
            if callable(log):
                log(f"SNAPSHOT_SKIP|{getattr(sym, 'value', sym)}|no decided thesis — not enterable (H1)")
            return None
        if self._last_daily_date is not None and snap["decision_date"] != self._last_daily_date:
            raise DegradedDataError(
                f"stale candidate snapshot for {getattr(sym, 'value', sym)}: decision_date="
                f"{snap['decision_date']} but last daily decision={self._last_daily_date} — a "
                f"missed daily→intraday handoff. Refusing to enter a stale thesis (#276b-0 H2, SG9)."
            )
        return snap

    def _decision_score_for(self, sym: Any) -> "int | None":
        snap = self._candidate_snapshot.get(sym)
        if snap is None:
            return None
        score = snap.get("score")
        return int(score) if score is not None else None

    def _inject_intraday_candidates(self, ictx: PhaseContext) -> None:
        snapshot = getattr(self, "_candidate_snapshot", {})
        if not snapshot:
            return
        pending = getattr(self, "_pending_entry_today", set())
        entered = getattr(self, "_entered_today", set())
        injected = 0
        for sym in snapshot:
            if self.portfolio[sym].invested or sym in pending or sym in entered:
                continue
            ictx.bar_state.sized_orders.append(
                OrderIntent(ticker=sym.value, qty=0, price=0.0, stop=0.0,
                            module="signal", risk_dollars=0.0)
            )
            ictx.record_funnel("injection_survives", sym)
            injected += 1
        if injected:
            log = getattr(self, "log", None)
            if callable(log):
                log(f"INTRADAY_INJECT|{self.time.date()}|candidates={injected}")

    def _mark_entry_pending(self, sym: Any) -> None:
        self._pending_entry_today.add(sym)

    def on_order_event(self, order_event: Any) -> None:
        sym = getattr(order_event, "symbol", None)
        if sym is None:
            return
        status = getattr(order_event, "status", None)
        if OrderStatus is None:
            return
        if sym in self._pending_entry_today and status in {
            OrderStatus.Filled, OrderStatus.PartiallyFilled, OrderStatus.Canceled, OrderStatus.Invalid
        }:
            self._pending_entry_today.discard(sym)
            if status in {OrderStatus.Filled, OrderStatus.PartiallyFilled}:
                self._entered_today.add(sym)
        if status == OrderStatus.Filled:
            meta = getattr(self, "_position_meta", {}).get(sym)
            ticket = meta.get("protective_stop_ticket") if meta else None
            if ticket is not None:
                ev_id = getattr(order_event, "order_id", getattr(order_event, "OrderId", None))
                tk_id = getattr(ticket, "order_id", getattr(ticket, "OrderId", None))
                if ev_id is not None and tk_id is not None and ev_id == tk_id:
                    self._position_meta.pop(sym, None)
                    self._pending_entry_today.discard(sym)

    def _ensure_funnel_state(self) -> None:
        if not hasattr(self, "_funnel_cum"):
            self._funnel_cum = {stage: 0 for stage in FUNNEL_STAGES}
        if not hasattr(self, "_funnel_today"):
            self._funnel_today = {stage: set() for stage in FUNNEL_INTRADAY_STAGES}
        if not hasattr(self, "_funnel_seen"):
            self._funnel_seen = {stage: set() for stage in FUNNEL_DISTINCT_STAGES}

    def _accumulate_daily_funnel(self, signal_winner_tickers: "list[str]", blocked: bool) -> None:
        self._ensure_funnel_state()
        n = len(signal_winner_tickers)
        self._funnel_cum["signal_winners"] += n
        if blocked:
            self._funnel_cum["regime_blocked_days"] += 1
        else:
            self._funnel_cum["regime_pass"] += n

    def _fold_intraday_funnel(self, ictx: Any) -> None:
        self._ensure_funnel_state()
        bar_funnel = getattr(ictx.bar_state, "funnel", {})
        for stage in FUNNEL_INTRADAY_STAGES:
            survivors = bar_funnel.get(stage)
            if survivors:
                self._funnel_today[stage].update(survivors)
        self._funnel_cum["orders"] += int(getattr(self.engine, "_fired_entries", 0))

    def _process_eod_funnel(self) -> None:
        if hasattr(self, "_funnel_today") and hasattr(self, "_funnel_cum"):
            self._flush_funnel_day()
            self._push_funnel_runtime_stats()

    def _flush_funnel_day(self) -> None:
        if not hasattr(self, "_funnel_seen"):
            self._funnel_seen = {stage: set() for stage in FUNNEL_DISTINCT_STAGES}
        for stage in FUNNEL_CANDIDATE_DAY_STAGES:
            self._funnel_cum[stage] += len(self._funnel_today[stage])
            self._funnel_today[stage] = set()
        for stage in FUNNEL_DISTINCT_STAGES:
            self._funnel_seen[stage] |= self._funnel_today[stage]
            self._funnel_cum[stage] = len(self._funnel_seen[stage])
            self._funnel_today[stage] = set()

    def _push_funnel_runtime_stats(self) -> None:
        setter = getattr(self, "set_runtime_statistic", None) or getattr(self, "SetRuntimeStatistic", None)
        if not callable(setter):
            return
        for stage in FUNNEL_STAGES:
            setter(f"funnel.{stage}", str(self._funnel_cum[stage]))
            setter(f"funnel._sem.{stage}", FUNNEL_STAGE_SEMANTICS[stage])

    def _clear_intraday_session_state(self) -> None:
        self._entry_confirm = {}
        self._pending_entry_today = set()
        self._entered_today = set()
        self._process_eod_funnel()

    def on_end_of_day(self, symbol: Any = None) -> None:
        self._clear_intraday_session_state()
