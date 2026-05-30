from AlgorithmImports import *
from datetime import timedelta

class TestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2025, 1, 1)
        self.set_end_date(2025, 3, 31)
        self.set_cash(100_000)
        self.set_warmup(timedelta(days=50))
        
        self.add_equity("SPY", Resolution.DAILY)
        self.add_equity("AAPL", Resolution.DAILY)
        
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 5),
            self._rebalance,
        )
    
    def _rebalance(self):
        if self.is_warming_up:
            return
        spy = self.securities["SPY"]
        aapl = self.securities["AAPL"]
        self.log(f"SPY={spy.price:.2f} AAPL={aapl.price:.2f}")
        if not self.portfolio.invested:
            self.set_holdings("SPY", 0.5)
            self.set_holdings("AAPL", 0.5)
