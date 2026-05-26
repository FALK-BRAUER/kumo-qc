"""
kumo-qc live trading algorithm — BCT Ichimoku methodology.
Runs on QuantConnect LEAN. Targets paper account DUK434934 (IBKR port 4002).
Live account U18777181 requires gate.py unlock + --parameter live-gate UNLOCKED.
"""

from AlgorithmImports import *
from bct_signal import score_symbol_native, _kijun


class LiveBCT(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2026, 1, 1)
        self.SetCash(50000)

        # Add ETFs explicitly (Morningstar fundamental data excludes ETFs)
        # These will be included in the BCT scoring universe
        etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
        for etf_symbol in etfs:
            self.AddEquity(etf_symbol)

        # Gate check — blocks live account without explicit unlock
        self.live_gate = self.GetParameter("live-gate") or "LOCKED"
        if self.LiveMode and self.live_gate != "UNLOCKED":
            self.Log("FIXME: live-gate not UNLOCKED. Trading halted.")
            self.Quit("live-gate LOCKED")

        # Universe: coarse filter 6k → ~200 by price + liquidity
        self.AddUniverse(self.CoarseFilter)

        # Rebalance weekly (Monday)
        self.Schedule.On(
            self.DateRules.WeekStart(),
            self.TimeRules.AfterMarketOpen("SPY", 30),
            self.Rebalance,
        )

        self._universe: list[Symbol] = []
        self._signals: dict[str, tuple[int, str]] = {}  # symbol → (score, rating)
        self._kijun_stops: dict[str, float] = {}
        self._indicators: dict[Symbol, IchimokuKinkoHyo] = {}
        self._weekly_indicators: dict[Symbol, IchimokuKinkoHyo] = {}

    def CoarseFilter(self, coarse):
        filtered = [
            c for c in coarse
            if c.HasFundamentalData
            and c.Price > 10
            and c.DollarVolume > 5_000_000
        ]
        filtered.sort(key=lambda c: c.DollarVolume, reverse=True)
        return [c.Symbol for c in filtered]

    def OnSecuritiesChanged(self, changes):
        for s in changes.AddedSecurities:
            sym = s.Symbol
            self._universe.append(sym)
            if sym not in self._indicators:
                self._indicators[sym] = self.ICHIMOKU(sym, 9, 26, 26, 52, 26, 26, Resolution.Daily)
            if sym not in self._weekly_indicators:
                w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
                consolidator = TradeBarConsolidator(Calendar.WEEKLY)
                def _on_weekly(_, bar: TradeBar) -> None:
                    w_ichi.update(bar)
                consolidator.data_consolidated += _on_weekly
                self.SubscriptionManager.AddConsolidator(sym, consolidator)
                self._weekly_indicators[sym] = w_ichi
        for s in changes.RemovedSecurities:
            sym = s.Symbol
            if sym in self._universe:
                self._universe.remove(sym)
            self._kijun_stops.pop(str(sym), None)
            if sym in self._indicators:
                self.DeregisterIndicator(self._indicators.pop(sym))
            if sym in self._weekly_indicators:
                self._weekly_indicators.pop(sym)
                # Note: We don't remove the consolidator to avoid complexity.

    def Rebalance(self):
        date_str = self.Time.strftime("%Y-%m-%d")
        self._signals = {}

        for symbol in sorted(self._universe):
            score, rating = score_symbol_native(self, symbol)
            if score >= 7:
                self._signals[symbol] = (score, rating)
                self.Log(f"SIGNAL|{date_str}|{symbol}|score={score}/8|rating={rating}")

        # Exit positions no longer in signal set
        for sym, holding in self.Portfolio.items():
            if holding.Invested and sym not in self._signals:
                self.Liquidate(sym)
                self.Log(f"EXIT|{date_str}|{sym}|reason=signal_lost")

        # Enter new signals (equal weight, max 10 positions)
        target_symbols = list(self._signals.keys())[:10]
        weight = 1.0 / max(len(target_symbols), 1)

        for symbol in target_symbols:
            self.SetHoldings(symbol, weight)
            self.Log(f"ENTRY|{date_str}|{symbol}|weight={weight:.3f}")
            self._set_kijun_stop(symbol)

    def _set_kijun_stop(self, symbol):
        try:
            hist = self.History(symbol, 30, self.Resolution.Daily)
            if hist.empty:
                return
            closes = hist.reset_index()["close"]
            kijun_val = float(_kijun(closes).iloc[-1])
            self._kijun_stops[str(symbol)] = kijun_val
        except Exception:
            pass

    def OnData(self, data: Slice):
        date_str = self.Time.strftime("%Y-%m-%d")
        for sym, holding in self.Portfolio.items():
            if not holding.Invested:
                continue
            
            price = self.Securities[sym].Price
            
            # Daily Kijun Stop
            stop = self._kijun_stops.get(str(sym))
            if stop is not None and price < stop:
                self.Liquidate(sym)
                self.Log(f"EXIT|{date_str}|{sym}|reason=kijun_stop|stop={stop:.2f}|price={price:.2f}")
                self._kijun_stops.pop(str(sym), None)
                continue

            # Daily Cloud Top Exit
            d_ichi = self._indicators.get(sym)
            if d_ichi is not None and d_ichi.IsReady:
                cloud_top = max(d_ichi.SenkouA.Current.Value, d_ichi.SenkouB.Current.Value)
                if price < cloud_top:
                    self.Liquidate(sym)
                    self.Log(f"EXIT|{date_str}|{sym}|reason=cloud_exit|cloud_top={cloud_top:.2f}|price={price:.2f}")
                    self._kijun_stops.pop(str(sym), None)
                    continue

            # Weekly Kijun Trail Exit
            w_ichi = self._weekly_indicators.get(sym)
            if w_ichi is not None and w_ichi.IsReady:
                w_kijun = w_ichi.Kijun.Current.Value
                if price < w_kijun:
                    self.Liquidate(sym)
                    self.Log(f"WEEKLY_KIJUN_STOP|{date_str}|{sym}|close={price:.2f}|w_kijun={w_kijun:.2f}")
                    self._kijun_stops.pop(str(sym), None)
                    continue
