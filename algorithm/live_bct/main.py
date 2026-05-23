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

        # Gate check — blocks live account without explicit unlock
        self.live_gate = self.GetParameter("live-gate") or "LOCKED"
        if self.LiveMode and self.live_gate != "UNLOCKED":
            self.Log("GATE: live-gate not UNLOCKED. Trading halted.")
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

    def CoarseFilter(self, coarse):
        filtered = [
            c for c in coarse
            if c.HasFundamentalData
            and c.Price > 10
            and c.DollarVolume > 5_000_000
        ]
        filtered.sort(key=lambda c: c.DollarVolume, reverse=True)
        return [c.Symbol for c in filtered[:200]]

    def OnSecuritiesChanged(self, changes):
        for s in changes.AddedSecurities:
            self._universe.append(s.Symbol)
        for s in changes.RemovedSecurities:
            sym = s.Symbol
            if sym in self._universe:
                self._universe.remove(sym)
            self._kijun_stops.pop(str(sym), None)

    def Rebalance(self):
        date_str = self.Time.strftime("%Y-%m-%d")
        self._signals = {}

        for symbol in self._universe:
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
            stop = self._kijun_stops.get(str(sym))
            if stop is None:
                continue
            price = self.Securities[sym].Price
            if price < stop:
                self.Liquidate(sym)
                self.Log(f"EXIT|{date_str}|{sym}|reason=kijun_stop|stop={stop:.2f}|price={price:.2f}")
                self._kijun_stops.pop(str(sym), None)
