from __future__ import annotations
"""
BCT performance backtest — parameterized date range.

Replicates live_bct.py trading logic for historical performance measurement:
≥7/8 BCT signal entry, 10% position sizing, Kijun stop exit, max 10 positions.

Date range set via QC parameters (start_year/month/day, end_year/month/day).
Defaults: 2025-01-01 to 2025-12-31 (FY2025).
Use scripts/run_windows.py to launch all 6-window + FY2025 backtests.

Uses QC native IchimokuKinkoHyo: daily registered via self.ichimoku(),
weekly via TradeBarConsolidator(Calendar.WEEKLY). Custom Wilder period-9
ADX retained in score_symbol_native() — QC native ADX is period 14.

Local mode: when LEAN data dir is detected, loads polygon_universe_equity200_fy2025.json
(326 unique tickers, top-200 S&P equity by dollar volume) instead of Morningstar CoarseFundamental filter.

G3 experiment: Phase 3 cloud-bottom trailing stop — after ≥56 calendar days held
AND unrealized PnL ≥ +15%, switch stop anchor from Kijun to cloud bottom
(min(Senkou_A, Senkou_B)). Extends winners; implements methodology.md §5 Rule #13 Phase 3.
"""

import json
from datetime import timedelta
from pathlib import Path

from AlgorithmImports import *  # noqa: F401,F403

try:
    from universe import EQUITY_200  # Cloud static universe (uploaded with main.py)
except ImportError:
    EQUITY_200 = []  # Fallback if universe.py not available

from typing import Any

import numpy as np
import pandas as pd


_WEEKLY_BARS = 130
_DAILY_BARS = 700


def _mid(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


def _adx_wilder(
    df: pd.DataFrame, period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX / +DI / -DI using Wilder's EWM (alpha = 1/period). Matches TC2000 / George's charts."""
    h, lo, c = df["high"], df["low"], df["close"]
    pc, ph, pl = c.shift(1), h.shift(1), lo.shift(1)
    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    up = h - ph
    dn = pl - lo
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up.values, 0.0), index=df.index, dtype=float)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn.values, 0.0), index=df.index, dtype=float)
    a = 1.0 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=a, adjust=False).mean()
    return adx, plus_di, minus_di


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    weekly = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return weekly.dropna(subset=["close"])


def _fetch_ohlcv(algorithm: Any, symbol: Any, bars: int, resolution: Any) -> pd.DataFrame:
    try:
        df = algorithm.History([symbol], bars, resolution)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.index, pd.MultiIndex):
        df = df.droplevel(0)
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def score_symbol(algorithm: Any, symbol: Any) -> dict[str, Any] | None:
    """History-based BCT scorer. Fetches 700 daily bars, resamples to weekly."""
    from QuantConnect import Resolution  # noqa: PLC0415

    daily = _fetch_ohlcv(algorithm, symbol, _DAILY_BARS, Resolution.DAILY)
    if len(daily) < 230:
        return None
    weekly = _resample_weekly(daily)
    if len(weekly) < 78:
        return None

    w_tenkan = _mid(weekly["high"], weekly["low"], 9)
    w_kijun  = _mid(weekly["high"], weekly["low"], 26)
    w_cloud_a = ((w_tenkan + w_kijun) / 2).shift(26)
    w_cloud_b = _mid(weekly["high"], weekly["low"], 52).shift(26)

    w_price        = weekly["close"].iloc[-1]
    w_cloud_a_now  = w_cloud_a.iloc[-1]
    w_cloud_b_now  = w_cloud_b.iloc[-1]
    w_tenkan_now   = w_tenkan.iloc[-1]
    w_kijun_now    = w_kijun.iloc[-1]
    w_price_26_ago = weekly["close"].iloc[-27]

    d_tenkan  = _mid(daily["high"], daily["low"], 9)
    d_kijun   = _mid(daily["high"], daily["low"], 26)
    d_cloud_a = ((d_tenkan + d_kijun) / 2).shift(26)
    d_cloud_b = _mid(daily["high"], daily["low"], 52).shift(26)

    d_price       = daily["close"].iloc[-1]
    d_tenkan_now  = d_tenkan.iloc[-1]
    d_cloud_a_now = d_cloud_a.iloc[-1]
    d_cloud_b_now = d_cloud_b.iloc[-1]
    ma200         = daily["close"].rolling(200).mean().iloc[-1]

    adx, plus_di, minus_di = _adx_wilder(daily, period=9)
    adx_now      = adx.iloc[-1]
    plus_di_now  = plus_di.iloc[-1]
    minus_di_now = minus_di.iloc[-1]
    adx_rising   = bool(adx.iloc[-1] > adx.iloc[-4])

    critical = [w_cloud_a_now, w_cloud_b_now, w_tenkan_now, w_kijun_now, w_price_26_ago,
                d_cloud_a_now, d_cloud_b_now, d_tenkan_now, ma200, adx_now, plus_di_now, minus_di_now]
    if any(pd.isna(v) for v in critical):
        return None

    conditions: list[bool] = [
        bool(w_price > max(w_cloud_a_now, w_cloud_b_now)),                        # 1. weekly above cloud top
        bool(w_tenkan_now > w_kijun_now),                                          # 2. weekly TK > KJ
        bool(w_price > w_price_26_ago),                                            # 3. weekly chikou
        bool(w_cloud_a_now > w_cloud_b_now),                                       # 4. weekly cloud green
        bool(d_price > max(d_cloud_a_now, d_cloud_b_now)),                        # 5. daily above cloud top
        bool(d_price > d_tenkan_now),                                              # 6. daily above tenkan
        bool(adx_rising and plus_di_now > minus_di_now and adx_now >= 20),        # 7. ADX
        bool(d_price > ma200),                                                     # 8. 200MA
    ]
    score = sum(conditions)
    if score == 8:   rating = "+++"
    elif score >= 6: rating = "++"
    elif score >= 4: rating = "+"
    elif score >= 2: rating = "="
    else:            rating = "--"
    return {"score": score, "rating": rating, "conditions": conditions}


def score_symbol_native(algorithm: Any, symbol: Any, ind: Any) -> dict[str, Any] | None:
    """Delegates to score_symbol (History-based)."""
    return score_symbol(algorithm, symbol)


class BCTUniverseFilter:
    """
    Plug into the main algorithm:

        self._universe_filter = BCTUniverseFilter()
        self.add_universe(
            self._universe_filter.coarse_selection,
            self._universe_filter.fine_selection,
        )
    """

    MIN_PRICE: float = 10.0
    MIN_DOLLAR_VOLUME: float = 5_000_000
    COARSE_MAX: int = 9999

    def __init__(self, algorithm=None) -> None:
        if algorithm is not None:
            self.COARSE_MAX = int(algorithm.get_parameter("coarse_max", "9999"))

    def coarse_selection(self, coarse: List[CoarseFundamental]) -> List[Symbol]:
        candidates = [
            c for c in coarse
            if c.has_fundamental_data
            and c.price >= self.MIN_PRICE
            and c.dollar_volume >= self.MIN_DOLLAR_VOLUME
        ]
        candidates.sort(key=lambda c: c.dollar_volume, reverse=True)
        return [c.symbol for c in candidates[: self.COARSE_MAX]]

    def fine_selection(self, fine: List[FineFundamental]) -> List[Symbol]:
        return [f.symbol for f in fine]


class BCTPerformanceAlgorithm(QCAlgorithm):

    MAX_POSITIONS: int = 9999  # unlimited — heat cap (POSITION_PCT) + cash check governs exposure
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 7
    # Exit condition flags — False = reference bct‑perf‑2020‑2026 (daily Kijun only)
    ENABLE_CLOUD_BREACH_EXIT: bool = False
    ENABLE_WEEKLY_KIJUN_EXIT: bool = False
    # Phase 3 stop progression (methodology.md §5 Rule #13)
    PHASE3_DAYS: int = 56         # calendar days before Phase 3 eligible
    PHASE3_PNL: float = 0.15      # unrealized PnL threshold for Phase 3

    @staticmethod
    def _find_local_data_dir() -> Path | None:
        candidates = [
            Path("/Lean/Data/equity/usa/daily"),
            Path("/Data/equity/usa/daily"),
            Path(__file__).parent.parent.parent / "data/equity/usa/daily",
        ]
        return next((d for d in candidates if d.exists()), None)

    @staticmethod
    def _load_polygon_universe() -> dict | None:
        candidates = [
            Path(__file__).parent / "polygon_universe_equity200_fy2025.json",
            Path("/Lean/Data/polygon_universe_equity200_fy2025.json"),
        ]
        for p in candidates:
            if p.exists():
                with open(p) as f:
                    return json.load(f)
        return None

    def initialize(self) -> None:
        self.log("VERSION_MARKER|e121_vix_ichimoku_2tier_v1")
        self.set_time_zone("America/New_York")
        self.log("VERSION_MARKER|cloud_static200_v15")
        sy = int(self.get_parameter("start_year",  "2025"))
        sm = int(self.get_parameter("start_month", "1"))
        sd = int(self.get_parameter("start_day",   "1"))
        ey = int(self.get_parameter("end_year",    "2025"))
        em = int(self.get_parameter("end_month",   "12"))
        ed = int(self.get_parameter("end_day",     "31"))
        self.set_start_date(sy, sm, sd)
        self.set_end_date(ey, em, ed)
        self.set_cash(100_000)
        self.set_benchmark("SPY")

        warmup_days = int(self.get_parameter("warmup_days", "750"))
        self.set_warmup(timedelta(days=warmup_days))
        self.warmup_days = warmup_days

        # Exit condition parameter overrides
        self.cloud_exit_enabled = self.get_parameter("cloud_exit", str(self.ENABLE_CLOUD_BREACH_EXIT)).lower() == "true"
        self.weekly_kijun_exit_enabled = self.get_parameter("weekly_kijun_exit", str(self.ENABLE_WEEKLY_KIJUN_EXIT)).lower() == "true"
        # E40c-v3: SPY > 50-day MA regime gate (faster regime than 200d)
        self.spy = self.add_equity("SPY", Resolution.DAILY)
        self.spy_sma50 = self.sma("SPY", 50)
        # E40d: gate on by default; override with regime_gate_enabled=false to disable
        _regime_param = self.get_parameter("regime_gate_enabled", "")
        self.regime_gate_enabled = _regime_param != "false"
        self.log("VERSION_MARKER|v3_spy_50ma")
        # E51: Parabolic entry block — skip entries on names with extreme 13-day run
        _parabolic_param = self.get_parameter("parabolic_threshold", "")
        if _parabolic_param != "":
            self.parabolic_threshold = float(_parabolic_param)
        else:
            self.parabolic_threshold = 0.25  # default 25%
        self.log(f"VERSION_MARKER|e51_parabolic_entry_block_v1|threshold={self.parabolic_threshold}")
        # E28: VIX percentile gate — block entries when VIX is in top X% of 2-year distribution
        _vix_pct_param = self.get_parameter("vix_percentile_enabled", "false")
        self.vix_percentile_enabled = _vix_pct_param.lower() == "true"
        if self.vix_percentile_enabled:
            _vix_pct_threshold = self.get_parameter("vix_percentile_threshold", "75.0")
            self.vix_percentile_threshold = float(_vix_pct_threshold)
            _vix_pct_lookback = self.get_parameter("vix_percentile_lookback", "504")
            self.vix_percentile_lookback = int(_vix_pct_lookback)
            self.log(f"VERSION_MARKER|e28_vix_percentile_gate_v1|threshold={self.vix_percentile_threshold}|lookback={self.vix_percentile_lookback}")
        self.vix = self.add_index("VIX", Resolution.DAILY).symbol
        # E121: VIX Ichimoku 2-tier gate — VIX cloud for dynamic slot sizing
        self.vix_ichi = self.ichimoku(self.vix, 9, 26, 26, 52, 26, 26)
        self.log("VERSION_MARKER|e121_vix_ichimoku_2tier_v1")

        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
        self._active: set = set()
        self._indicators: dict = {}
        self._polygon_universe: dict | None = None
        self._position_meta: dict = {}  # symbol → {entry_date, entry_price}

        poly = self._load_polygon_universe()
        if poly is not None:
            # Local: static universe from Polygon daily snapshot (867 unique tickers, FY2025)
            if True:  # scope block
                self._polygon_universe = poly
                all_tickers: set[str] = set()
                for tickers in poly.values():
                    all_tickers.update(tickers)
                self.log(f"LOCAL_UNIVERSE|polygon_equity|unique_tickers={len(all_tickers)}")
                for ticker in sorted(all_tickers):
                    try:
                        self.add_equity(ticker, Resolution.DAILY)
                    except Exception:
                        pass
            # (dead code — outer check ensures poly is not None here)
        else:
            # Cloud: load polygon-326 universe from ObjectStore (same as local)
            obj_key = "polygon_universe_equity200_fy2025.json"
            if self.object_store.contains_key(obj_key):
                cloud_poly = json.loads(self.object_store.read(obj_key))
                all_tickers = sorted({t for tickers in cloud_poly.values() for t in tickers})
                self.log(f"CLOUD_UNIVERSE|object_store|unique_tickers={len(all_tickers)}")
                for ticker in all_tickers:
                    try:
                        self.add_equity(ticker, Resolution.DAILY)
                    except Exception:
                        pass
            else:
                # Fallback if ObjectStore upload not done
                self.log("CLOUD_UNIVERSE|object_store_missing|fallback_SPY_ETF")
                spy = Symbol.create("SPY", SecurityType.EQUITY, Market.USA)
                self.add_universe(self.universe.etf(spy, self.universe_settings))

        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 5),
            self._rebalance,
        )

    def on_securities_changed(self, changes: SecurityChanges) -> None:
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
                del self._indicators[sym]

    def _register_indicators(self, sym) -> None:
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)

        w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
        w_close = RollingWindow[float](28)

        consolidator = TradeBarConsolidator(Calendar.WEEKLY)

        def _on_weekly(_, bar: TradeBar) -> None:
            w_ichi.update(bar)
            w_close.add(bar.close)

        consolidator.data_consolidated += _on_weekly
        self.subscription_manager.add_consolidator(sym, consolidator)

        # With 750-day warmup, consolidator receives sufficient weekly bars automatically.
        # Skip manual seed during warmup to avoid 326× history() calls at init time.
        if not self.is_warming_up:
            self._seed_weekly(sym, w_ichi, w_close)

        self._indicators[sym] = {
            "d_ichi": d_ichi,
            "w_ichi": w_ichi,
            "w_close": w_close,
            "sma200": sma200,
            "consolidator": consolidator,
        }

    def _seed_weekly(self, sym, w_ichi, w_close) -> None:
        hist = self.history(sym, 750, Resolution.DAILY)
        if hist is None or hist.empty:
            return
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        if not {"open", "high", "low", "close", "volume"}.issubset(hist.columns):
            return
        # P0 fix: avoid DataFrame.resample() timeout on QC cloud (5-min limit).
        # Manual weekly aggregation — same result as resample("W-FRI")
        # but avoids pandas resample overhead that triggers QC timeout.
        weeks: dict = {}
        for time, row in hist.iterrows():
            # Friday of this week
            friday = time + pd.Timedelta(days=(4 - time.weekday()) % 7)
            friday = friday.normalize()
            if friday not in weeks:
                weeks[friday] = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                }
            else:
                weeks[friday]["high"] = max(weeks[friday]["high"], float(row["high"]))
                weeks[friday]["low"] = min(weeks[friday]["low"], float(row["low"]))
                weeks[friday]["close"] = float(row["close"])
                weeks[friday]["volume"] += int(row["volume"])

        for time in sorted(weeks):
            row = weeks[time]
            bar = TradeBar(
                time, sym,
                row["open"], row["high"],
                row["low"], row["close"],
                row["volume"], timedelta(weeks=1),
            )
            w_ichi.update(bar)
            w_close.add(float(row["close"]))

    def _daily_vals(self, symbol) -> tuple[float, float, float, float] | None:
        """Returns (close, kijun, cloud_top, cloud_bottom)."""
        if symbol not in self._indicators:
            return None
        d_ichi = self._indicators[symbol]["d_ichi"]
        if not d_ichi.is_ready:
            return None
        close = float(self.securities[symbol].close)
        kijun = d_ichi.kijun.current.value
        senkou_a = d_ichi.senkou_a.current.value
        senkou_b = d_ichi.senkou_b.current.value
        return close, kijun, max(senkou_a, senkou_b), min(senkou_a, senkou_b)

    def _has_open_orders(self, symbol) -> bool:
        return bool(self.transactions.get_open_orders(symbol))

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        date_str = self.time.strftime("%Y-%m-%d")

        for symbol, holding in list(self.portfolio.items()):
            if not holding.invested or self._has_open_orders(symbol):
                continue
            vals = self._daily_vals(symbol)
            if vals is None:
                continue
            close, kijun, cloud_top, cloud_bottom = vals

            w_ichi = self._indicators[symbol]["w_ichi"]
            w_kijun = w_ichi.kijun.current.value if w_ichi.is_ready else None

            # Determine stop anchor: Phase 3 (≥56 days + ≥15% gain) → cloud bottom
            meta = self._position_meta.get(symbol)
            in_phase3 = False
            if meta is not None:
                days_held = (self.time - meta["entry_date"]).days
                pnl_pct = close / meta["entry_price"] - 1
                if days_held >= self.PHASE3_DAYS and pnl_pct >= self.PHASE3_PNL:
                    in_phase3 = True

            if in_phase3:
                if close < cloud_bottom:
                    self.market_on_open_order(symbol, -holding.quantity)
                    meta = self._position_meta.pop(symbol, {})
                    days_h = (self.time - meta.get("entry_date", self.time)).days
                    pnl_h = close / meta.get("entry_price", close) - 1
                    self.log(f"PHASE3_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_bottom={cloud_bottom:.2f}|days={days_h}|pnl={pnl_h:.1%}")
            else:
                if close < kijun:
                    self.market_on_open_order(symbol, -holding.quantity)
                    self._position_meta.pop(symbol, None)
                    self.log(f"STOP|{date_str}|{symbol.value}|close={close:.2f}|kijun={kijun:.2f}")
                elif self.cloud_exit_enabled and close < cloud_top:
                    self.market_on_open_order(symbol, -holding.quantity)
                    self._position_meta.pop(symbol, None)
                    self.log(f"CLOUD_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_top={cloud_top:.2f}")
                elif self.weekly_kijun_exit_enabled and w_kijun is not None and close < w_kijun:
                    self.market_on_open_order(symbol, -holding.quantity)
                    self._position_meta.pop(symbol, None)
                    self.log(f"WEEKLY_KIJUN_STOP|{date_str}|{symbol.value}|close={close:.2f}|w_kijun={w_kijun:.2f}")

        # E121: VIX Ichimoku 2-tier slot gate — no full block, only capacity reduction
        max_positions = self.MAX_POSITIONS
        if self.regime_gate_enabled and self.securities.contains_key(self.vix) and self.vix_ichi.is_ready:
            vix_price = float(self.securities[self.vix].price)
            vix_cloud_top = max(self.vix_ichi.senkou_a.current.value, self.vix_ichi.senkou_b.current.value)
            if vix_price > vix_cloud_top:
                max_positions = 9999  # Tier 2: no slot cap, cash governs
                tier = 2
            else:
                tier = 1
            self.log(f"VIX_TIER|{date_str}|VIX={vix_price:.2f}|cloud_top={vix_cloud_top:.2f}|tier={tier}|max_positions={max_positions}")

        # E28: VIX percentile gate — block entries when VIX is in top X% of 2-year distribution
        if self.vix_percentile_enabled and self.securities.contains_key(self.vix):
            try:
                vix_hist = self.history(self.vix, self.vix_percentile_lookback, Resolution.DAILY)
                if vix_hist is not None and len(vix_hist) >= int(self.vix_percentile_lookback * 0.8):
                    if isinstance(vix_hist.index, pd.MultiIndex):
                        vix_hist = vix_hist.droplevel(0)
                    close_col = "close" if "close" in vix_hist.columns else "Close"
                    vix_series = vix_hist[close_col].dropna()
                    if len(vix_series) > 0:
                        vix_price_now = float(self.securities[self.vix].price)
                        vix_pct = (vix_series < vix_price_now).mean() * 100.0
                        blocked = vix_pct > self.vix_percentile_threshold
                        self.log(f"VIX_PERCENTILE|{date_str}|VIX={vix_price_now:.2f}|2yr_pct={vix_pct:.1f}|threshold={self.vix_percentile_threshold}|blocked={blocked}")
                        if blocked:
                            return
            except Exception:
                pass

        exiting = {
            o.symbol
            for o in self.transactions.get_open_orders()
            if o.quantity < 0
        }
        open_count = sum(
            1 for sym, h in self.portfolio.items()
            if h.invested and sym not in exiting
        )
        slots = max_positions - open_count
        if slots <= 0:
            return

        # E40c-v3: SPY regime gate — block entries when SPY below 50d SMA
        if self.spy_sma50.is_ready:
            spy_price = float(self.securities[self.spy].price)
            spy_ma50 = float(self.spy_sma50.current.value)
            if spy_price < spy_ma50:
                self.log(f"REGIME_BLOCK|{date_str}|SPY={spy_price:.2f}|MA50={spy_ma50:.2f}")
                return

        # When running locally with polygon universe, restrict candidates to today's snapshot
        today_poly: set[str] | None = None
        if self._polygon_universe is not None:
            today_poly = set(self._polygon_universe.get(date_str, []))

        candidates: list[tuple] = []
        for symbol in sorted(self._active):
            if today_poly is not None and symbol.value not in today_poly:
                continue
            if self.portfolio[symbol].invested:
                continue
            if self._has_open_orders(symbol):
                continue
            ind = self._indicators.get(symbol)
            if ind is None:
                continue
            # === PRE-FILTER: skip symbols that cannot reach MIN_SCORE=7 ===
            sma200_ind = ind.get("sma200")
            d_ichi_ind = ind.get("d_ichi")
            if (sma200_ind and sma200_ind.is_ready and d_ichi_ind and d_ichi_ind.is_ready):
                price = float(self.securities[symbol].price)
                if price <= 0:
                    continue
                # If below SMA200, condition 8 fails → max score 6 → skip (MIN_SCORE=7)
                if price < sma200_ind.current.value:
                    continue
                # If below daily cloud, condition 5 fails → max score 6 → skip
                cloud_top = max(d_ichi_ind.senkou_a.current.value, d_ichi_ind.senkou_b.current.value)
                if price < cloud_top:
                    continue
            # === END PRE-FILTER ===
            result = score_symbol_native(self, symbol, ind)
            if result is None or result["score"] < self.MIN_SCORE:
                continue
            # E51: Parabolic entry block — skip if 13-day return exceeds threshold
            try:
                hist = self.history(symbol, 14, Resolution.DAILY)
                if hist is not None and len(hist) >= 14:
                    if isinstance(hist.index, pd.MultiIndex):
                        hist = hist.droplevel(0)
                    close_col = "close" if "close" in hist.columns else "Close"
                    price_13d_ago = float(hist.iloc[0][close_col])
                    current_price = float(hist.iloc[-1][close_col])
                    if price_13d_ago > 0:
                        return_13d = current_price / price_13d_ago - 1
                        if return_13d > self.parabolic_threshold:
                            self.log(f"PARABOLIC_BLOCK|{date_str}|{symbol.value}|13d_return={return_13d:.2%}|threshold={self.parabolic_threshold:.2%}")
                            continue
            except Exception:
                pass
            # Tiebreak metric: dollar-volume proxy = mean(close*volume) over 20 daily bars.
            # Deterministic + liquidity-based. Fixes prior bug where score ties broke
            # ALPHABETICALLY (stable sort on A-Z candidate order) → only first 10 names bought.
            dollar_volume = 0.0
            try:
                dv_hist = self.history(symbol, 20, Resolution.DAILY)
                if dv_hist is not None and len(dv_hist) >= 1:
                    if isinstance(dv_hist.index, pd.MultiIndex):
                        dv_hist = dv_hist.droplevel(0)
                    _cc = "close" if "close" in dv_hist.columns else "Close"
                    _vc = "volume" if "volume" in dv_hist.columns else "Volume"
                    if _vc in dv_hist.columns:
                        dollar_volume = float((dv_hist[_cc] * dv_hist[_vc]).mean())
            except Exception:
                dollar_volume = 0.0
            candidates.append((symbol, result["score"], dollar_volume))

        # Primary: score DESC. Tiebreak: dollar-volume DESC. NEVER alphabetical.
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        committed_cash = 0.0  # track cash committed this rebalance before fills execute
        available_cash = float(self.portfolio.cash)
        for symbol, score, _dv in candidates[:slots]:
            price = self.securities[symbol].price
            if price <= 0:
                continue
            target_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
            if available_cash - committed_cash < target_value:  # heat cap — stop when cash exhausted
                self.log(f"SKIP|{date_str}|{symbol.value}|cash_exhausted|remaining={available_cash - committed_cash:.2f}")
                break
            quantity = int(target_value / price)
            if quantity <= 0:
                continue
            committed_cash += target_value
            self.market_on_open_order(symbol, quantity)
            self._position_meta[symbol] = {"entry_date": self.time, "entry_price": float(price)}
            self.log(f"ENTRY|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|price~{price:.2f}")

        self.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={min(len(candidates), slots)}")
