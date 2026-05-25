from __future__ import annotations
"""
Minimal BCT backtest — hardcoded universe, no Morningstar/fundamental data.

Purpose: local + QC cloud parity baseline that bypasses has_fundamental_data=True
blocker (GH #14/#16). Proves the BCT scoring and execution logic works end-to-end
without the coarse/fine universe filter.

Universe: SPY, QQQ, AAPL (hardcoded via AddEquity).
Signal: same 8-condition BCT Blue Flag checklist as performance_bct.
Exits: daily Kijun stop (reference baseline) + optional cloud breach + weekly Kijun.
Parameters: warmup_days (default 750), cloud_exit (default false), weekly_kijun_exit (default false).
"""

from datetime import timedelta

from AlgorithmImports import *  # noqa: F401,F403

from bct_signal import score_symbol


class BCTMinimalAlgorithm(QCAlgorithm):

    MAX_POSITIONS: int = 10
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 7

    UNIVERSE: list[str] = [
        # Core indices
        "SPY", "QQQ",
        # Large-cap tech/growth
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL", "NFLX",
        # Sector ETFs
        "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU",
    ]

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

        # Exit condition parameters (default: disabled for reference baseline)
        self.cloud_exit_enabled = self.get_parameter("cloud_exit", "false").lower() == "true"
        self.weekly_kijun_exit_enabled = self.get_parameter("weekly_kijun_exit", "false").lower() == "true"

        self.universe_settings.resolution = Resolution.DAILY
        self._indicators: dict = {}
        for ticker in self.UNIVERSE:
            sym = self.add_equity(ticker, Resolution.DAILY).symbol
            self._register_indicators(sym)

        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 5),
            self._rebalance,
        )

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

    def _has_open_orders(self, symbol) -> bool:
        return bool(self.transactions.get_open_orders(symbol))

    def _daily_close_and_kijun_and_cloud_top(self, symbol) -> tuple[float, float, float] | None:
        """Fetch daily close, Kijun-sen, and cloud top for exit logic."""
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

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        date_str = self.time.strftime("%Y-%m-%d")

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
            elif self.cloud_exit_enabled and close < cloud_top:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"CLOUD_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_top={cloud_top:.2f}")
            elif self.weekly_kijun_exit_enabled and w_kijun is not None and close < w_kijun:
                self.market_on_open_order(symbol, -holding.quantity)
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

        candidates: list[tuple] = []
        for ticker in self.UNIVERSE:
            symbol = self.symbol(ticker)
            if self.portfolio[symbol].invested:
                continue
            
            # === PRE-FILTER: skip symbols that cannot reach MIN_SCORE ===
            ind = self._indicators.get(symbol)
            if ind is not None:
                sma200_ind = ind.get("sma200")
                d_ichi_ind = ind.get("d_ichi")
                if (sma200_ind and sma200_ind.is_ready and 
                    d_ichi_ind and d_ichi_ind.is_ready):
                    price = float(self.securities[symbol].price)
                    if price <= 0:
                        continue
                    # Condition 8: price > SMA200
                    if price < sma200_ind.current.value:
                        continue
                    # Condition 5: price > daily cloud top
                    cloud_top = max(d_ichi_ind.senkou_a.current.value, 
                                   d_ichi_ind.senkou_b.current.value)
                    if price < cloud_top:
                        continue
            # === END PRE-FILTER ===
            
            result = score_symbol(self, symbol)
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
            self.log(f"ENTRY|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|price~{price:.2f}")

        self.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={min(len(candidates), slots)}")
