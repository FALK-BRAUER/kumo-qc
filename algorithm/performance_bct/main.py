"""
BCT performance backtest — QC project 32034565 (performance_bct).
Full order simulation for return/drawdown/Sharpe analysis.
Uses BCT score ≥7 for entry, Kijun stop for exit. Equal weight, max 10 positions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from AlgorithmImports import *
from bct_signal import score_symbol_native, _kijun


class PerformanceBCT(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2025, 1, 1)
        self.SetEndDate(2026, 5, 22)
        self.SetCash(100000)
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage)

        self.Settings.RebalancePortfolioOnInsightChanges = False
        self.Settings.RebalancePortfolioOnSecurityChanges = False

        self.AddUniverse(self.CoarseFilter)

        self.Schedule.On(
            self.DateRules.WeekStart(),
            self.TimeRules.AfterMarketOpen("SPY", 30),
            self.Rebalance,
        )

        self._universe: list[Symbol] = []
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
        signals: dict[Symbol, tuple[int, str]] = {}

        for symbol in self._universe:
            score, rating = score_symbol_native(self, symbol)
            if score >= 7:
                signals[symbol] = (score, rating)
                self.Log(f"SIGNAL|{date_str}|{symbol}|score={score}/8|rating={rating}")

        # Exit dropped signals
        for sym, holding in self.Portfolio.items():
            if holding.Invested and sym not in signals:
                self.Liquidate(sym)
                self.Log(f"EXIT|{date_str}|{sym}|reason=signal_lost")

        # Enter / rebalance
        target_list = sorted(signals.keys(), key=lambda s: signals[s][0], reverse=True)[:10]
        weight = 1.0 / max(len(target_list), 1)

        for symbol in target_list:
            self.SetHoldings(symbol, weight)
            self.Log(f"ENTRY|{date_str}|{symbol}|weight={weight:.3f}")
            self._update_kijun_stop(symbol)

    def _update_kijun_stop(self, symbol):
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
            if self.Securities[sym].Price < stop:
                self.Liquidate(sym)
                self.Log(f"EXIT|{date_str}|{sym}|reason=kijun_stop")
                self._kijun_stops.pop(str(sym), None)

    def OnEndOfAlgorithm(self):
        self.Log(f"FINAL|portfolio_value={self.Portfolio.TotalPortfolioValue:.2f}")
        self.Log(f"FINAL|total_return={(self.Portfolio.TotalPortfolioValue - 100000) / 100000 * 100:.2f}%")
