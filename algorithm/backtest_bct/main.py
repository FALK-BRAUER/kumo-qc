"""
BCT backtest signal audit — QC project 32033824 (backtest_bct).
Pure signal logger, no order placement. Used for Phase 4 validation.
Compares BCT signal output against kumo-trader scanner CSV results.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from AlgorithmImports import *
from bct_signal import score_symbol_native


class BacktestBCT(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2026, 5, 8)
        self.SetEndDate(2026, 5, 22)
        self.SetCash(100000)
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage)

        # Universe: same coarse filter as live_bct
        self.AddUniverse(self.CoarseFilter)

        self.Schedule.On(
            self.DateRules.WeekStart(),
            self.TimeRules.AfterMarketOpen("SPY", 30),
            self.ScoreAndLog,
        )

        self._universe: list[Symbol] = []

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
            if s.Symbol in self._universe:
                self._universe.remove(s.Symbol)

    def ScoreAndLog(self):
        date_str = self.Time.strftime("%Y-%m-%d")
        for symbol in self._universe:
            score, rating = score_symbol_native(self, symbol)
            if score >= 6:
                self.Log(f"SIGNAL|{date_str}|{symbol}|score={score}/8|rating={rating}")

    def OnData(self, data: Slice):
        pass
