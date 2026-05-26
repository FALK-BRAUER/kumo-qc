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

R2 experiment: stagnation rotation — exit held positions with
  days_held >= 10 AND pnl < -2% if a candidate with equal or higher score exists.
"""

from datetime import timedelta
from pathlib import Path

from AlgorithmImports import *  # noqa: F401,F403

from bct_signal import score_symbol_native
from universe_filter import BCTUniverseFilter

STAGNATION_DAYS = 10
STAGNATION_PNL_THRESHOLD = -0.02


class BCTPerformanceAlgorithm(QCAlgorithm):

    MAX_POSITIONS: int = 10
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 7
    ENABLE_CLOUD_BREACH_EXIT: bool = False
    ENABLE_WEEKLY_KIJUN_EXIT: bool = False

    def initialize(self) -> None:
        self.set_time_zone("America/New_York")
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

        self.cloud_exit_enabled = self.get_parameter("cloud_exit", str(self.ENABLE_CLOUD_BREACH_EXIT)).lower() == "true"
        self.weekly_kijun_exit_enabled = self.get_parameter("weekly_kijun_exit", str(self.ENABLE_WEEKLY_KIJUN_EXIT)).lower() == "true"

        etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
        for etf_symbol in etfs:
            self.add_equity(etf_symbol)

        self.universe_settings.resolution = Resolution.DAILY

        self._filter = BCTUniverseFilter()
        self._active: set = set()
        self._indicators: dict = {}
        self._position_meta: dict = {}  # symbol → {entry_date, entry_price, score}

        _dyn_file = Path(__file__).parent / "polygon_universe_equity200_fy2025.json"
        if _dyn_file.exists():
            import json as _json
            with open(_dyn_file) as _f:
                self._daily_universe: dict = _json.load(_f)
            _all_tickers: set = set()
            for _tickers in self._daily_universe.values():
                _all_tickers.update(_tickers)
            for _ticker in sorted(_all_tickers):
                try:
                    self.add_equity(_ticker, Resolution.DAILY)
                except Exception:
                    pass
        else:
            self._daily_universe = {}
            self.add_universe(
                self._filter.coarse_selection,
                self._filter.fine_selection,
            )

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
        weekly = hist.resample("W-FRI").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna(subset=["close"])
        for time, row in weekly.iterrows():
            bar = TradeBar(
                time, sym,
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"]), timedelta(weeks=1),
            )
            w_ichi.update(bar)
            w_close.add(float(row["close"]))

    def _daily_close_and_kijun_and_cloud_top(self, symbol) -> tuple[float, float, float] | None:
        if symbol not in self._indicators:
            return None
        d_ichi = self._indicators[symbol]["d_ichi"]
        if not d_ichi.is_ready:
            return None
        close = float(self.securities[symbol].price)
        kijun = d_ichi.kijun.current.value
        senkou_a = d_ichi.senkou_a.current.value
        senkou_b = d_ichi.senkou_b.current.value
        cloud_top = max(senkou_a, senkou_b)
        return close, kijun, cloud_top

    def _has_open_orders(self, symbol) -> bool:
        return bool(self.transactions.get_open_orders(symbol))

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        date_str = self.time.strftime("%Y-%m-%d")
        today_universe = set(self._daily_universe.get(date_str, []))

        # === SCORE ALL CANDIDATES (non-invested, not open orders) ===
        all_candidates: list[tuple] = []
        for symbol in sorted(self._active):
            if today_universe and symbol.value not in today_universe:
                continue
            if self.portfolio[symbol].invested:
                continue
            if self._has_open_orders(symbol):
                continue
            ind = self._indicators.get(symbol)
            if ind is None:
                continue
            sma200_ind = ind.get("sma200")
            d_ichi_ind = ind.get("d_ichi")
            if sma200_ind and sma200_ind.is_ready and d_ichi_ind and d_ichi_ind.is_ready:
                price = float(self.securities[symbol].price)
                if price <= 0:
                    continue
                if price < sma200_ind.current.value:
                    continue
                cloud_top_val = max(d_ichi_ind.senkou_a.current.value, d_ichi_ind.senkou_b.current.value)
                if price < cloud_top_val:
                    continue
            result = score_symbol_native(self, symbol, ind)
            if result is None or result["score"] < self.MIN_SCORE:
                continue
            all_candidates.append((symbol, result["score"]))
        all_candidates.sort(key=lambda x: x[1], reverse=True)
        best_candidate_score = all_candidates[0][1] if all_candidates else 0

        # === STANDARD EXITS (Kijun stop, cloud, weekly Kijun) ===
        for symbol, holding in list(self.portfolio.items()):
            if not holding.invested or self._has_open_orders(symbol):
                continue
            vals = self._daily_close_and_kijun_and_cloud_top(symbol)
            if vals is None:
                continue
            close, kijun, cloud_top = vals
            w_ichi = self._indicators[symbol]["w_ichi"]
            w_kijun = w_ichi.kijun.current.value if w_ichi.is_ready else None

            if close < kijun:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"STOP|{date_str}|{symbol.value}|close={close:.2f}|kijun={kijun:.2f}")
                self._position_meta.pop(symbol, None)
            elif self.cloud_exit_enabled and close < cloud_top:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"CLOUD_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_top={cloud_top:.2f}")
                self._position_meta.pop(symbol, None)
            elif self.weekly_kijun_exit_enabled and w_kijun is not None and close < w_kijun:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"WEEKLY_KIJUN_STOP|{date_str}|{symbol.value}|close={close:.2f}|w_kijun={w_kijun:.2f}")
                self._position_meta.pop(symbol, None)

        # === STAGNATION ROTATION EXITS ===
        if best_candidate_score > 0:
            for symbol, holding in list(self.portfolio.items()):
                if not holding.invested or self._has_open_orders(symbol):
                    continue
                meta = self._position_meta.get(symbol)
                if meta is None:
                    continue
                days_held = (self.time - meta["entry_date"]).days
                if days_held < STAGNATION_DAYS:
                    continue
                price = float(self.securities[symbol].price)
                pnl_pct = price / meta["entry_price"] - 1
                if pnl_pct >= STAGNATION_PNL_THRESHOLD:
                    continue
                if best_candidate_score >= meta["score"]:
                    self.market_on_open_order(symbol, -holding.quantity)
                    self.log(
                        f"ROTATION_EXIT|{date_str}|{symbol.value}"
                        f"|days={days_held}|pnl={pnl_pct:.1%}"
                        f"|held_score={meta['score']}|best_cand={best_candidate_score}"
                    )
                    self._position_meta.pop(symbol, None)

        # === NEW ENTRIES ===
        exiting = {
            o.symbol
            for o in self.transactions.get_open_orders()
            if o.quantity < 0
        }
        open_count = sum(
            1 for sym, h in self.portfolio.items()
            if h.invested and sym not in exiting
        )
        slots = self.MAX_POSITIONS - open_count
        if slots <= 0:
            return

        new_entries = 0
        for symbol, score in all_candidates[:slots]:
            price = self.securities[symbol].price
            if price <= 0:
                continue
            target_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
            quantity = int(target_value / price)
            if quantity <= 0:
                continue
            self.market_on_open_order(symbol, quantity)
            self._position_meta[symbol] = {
                "entry_date": self.time,
                "entry_price": float(price),
                "score": score,
            }
            self.log(f"ENTRY|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|price~{price:.2f}")
            new_entries += 1

        self.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={new_entries}")
