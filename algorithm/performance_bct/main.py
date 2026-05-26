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

from bct_signal import score_symbol_native
from universe_filter import BCTUniverseFilter


class BCTPerformanceAlgorithm(QCAlgorithm):

    MAX_POSITIONS: int = 10
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 7
    # Exit condition flags — False = reference bct‑perf‑2020‑2026 (daily Kijun only)
    ENABLE_CLOUD_BREACH_EXIT: bool = False
    ENABLE_WEEKLY_KIJUN_EXIT: bool = False
    # Phase 2/3 stop progression (methodology.md §5 Rule #13)
    PHASE2_DAYS: int = 28         # calendar days before Phase 2 extension eligible
    PHASE2_PNL: float = 0.05      # unrealized PnL threshold for Phase 2 extension
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

        # Exit condition parameter overrides
        self.cloud_exit_enabled = self.get_parameter("cloud_exit", str(self.ENABLE_CLOUD_BREACH_EXIT)).lower() == "true"
        self.weekly_kijun_exit_enabled = self.get_parameter("weekly_kijun_exit", str(self.ENABLE_WEEKLY_KIJUN_EXIT)).lower() == "true"

        self.universe_settings.resolution = Resolution.DAILY
        self._active: set = set()
        self._indicators: dict = {}
        self._polygon_universe: dict | None = None
        self._position_meta: dict = {}  # symbol → {entry_date, entry_price}

        if self._find_local_data_dir() is not None:
            # Local: static universe from Polygon daily snapshot (867 unique tickers, FY2025)
            poly = self._load_polygon_universe()
            if poly is not None:
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
            else:
                # Fallback: ETFs only (no polygon JSON found)
                self.log("LOCAL_UNIVERSE|fallback_etf_only|polygon_json_not_found")
                etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC", "SPY"]
                for etf in etfs:
                    self.add_equity(etf, Resolution.DAILY)
        else:
            # Cloud: dynamic universe via Morningstar CoarseFundamental + ETFs
            etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
            for etf in etfs:
                self.add_equity(etf, Resolution.DAILY)
            self._filter = BCTUniverseFilter()
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

            # Determine stop phase: Phase 3 (≥56d + ≥15%) > Phase 2 ext (≥28d + ≥5%) > default Kijun
            meta = self._position_meta.get(symbol)
            in_phase3 = False
            in_phase2_ext = False
            if meta is not None:
                days_held = (self.time - meta["entry_date"]).days
                pnl_pct = close / meta["entry_price"] - 1
                if days_held >= self.PHASE3_DAYS and pnl_pct >= self.PHASE3_PNL:
                    in_phase3 = True
                elif days_held >= self.PHASE2_DAYS and pnl_pct >= self.PHASE2_PNL:
                    in_phase2_ext = True

            if in_phase3:
                if close < cloud_bottom:
                    self.market_on_open_order(symbol, -holding.quantity)
                    meta = self._position_meta.pop(symbol, {})
                    days_h = (self.time - meta.get("entry_date", self.time)).days
                    pnl_h = close / meta.get("entry_price", close) - 1
                    self.log(f"PHASE3_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_bottom={cloud_bottom:.2f}|days={days_h}|pnl={pnl_h:.1%}")
            elif in_phase2_ext:
                if close < cloud_bottom:
                    self.market_on_open_order(symbol, -holding.quantity)
                    meta = self._position_meta.pop(symbol, {})
                    days_h = (self.time - meta.get("entry_date", self.time)).days
                    pnl_h = close / meta.get("entry_price", close) - 1
                    self.log(f"PHASE2_EXTENSION_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_bottom={cloud_bottom:.2f}|days={days_h}|pnl={pnl_h:.1%}")
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
            candidates.append((symbol, result["score"]))

        candidates.sort(key=lambda x: x[1], reverse=True)
        for symbol, score in candidates[:slots]:
            price = self.securities[symbol].price
            if price <= 0:
                continue
            target_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
            quantity = int(target_value / price)
            if quantity <= 0:
                continue
            self.market_on_open_order(symbol, quantity)
            self._position_meta[symbol] = {"entry_date": self.time, "entry_price": float(price)}
            self.log(f"ENTRY|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|price~{price:.2f}")

        self.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={min(len(candidates), slots)}")
