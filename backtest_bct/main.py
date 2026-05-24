"""
Phase 4: BCT backtest validation — pure signal audit, no orders placed.

Saves results to QC Object Store as JSON (key: "bct_signals") so they
can be retrieved via the Object Store API after the backtest completes.
Also logs SIGNAL lines via self.log() for debugging.

Output format in object store:
  {
    "date": [ {"ticker": ..., "score": ..., "rating": ..., "conditions": [...]}, ... ],
    ...
  }
"""
import json

from AlgorithmImports import *  # noqa: F401,F403

from bct_signal import score_symbol
from universe_filter import BCTUniverseFilter


class BCTBacktestAlgorithm(QCAlgorithm):

    def initialize(self) -> None:
        self.set_time_zone("America/New_York")
        self.set_start_date(2026, 5, 12)
        self.set_end_date(2026, 5, 16)
        self.set_cash(100_000)
        self.set_benchmark("SPY")

        self.universe_settings.resolution = Resolution.DAILY

        self._filter = BCTUniverseFilter()
        self._active: set = set()
        self._signals: dict = {}  # date -> list of signal dicts

        self.add_universe(
            self._filter.coarse_selection,
            self._filter.fine_selection,
        )

        # 4:05 PM ET — daily bars settled, safe to call History()
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 5),
            self._audit_signals,
        )

    def on_securities_changed(self, changes: SecurityChanges) -> None:
        for s in changes.added_securities:
            self._active.add(s.symbol)
        for s in changes.removed_securities:
            self._active.discard(s.symbol)

    def _audit_signals(self) -> None:
        date_str = self.time.strftime("%Y-%m-%d")
        day_signals = []

        for symbol in list(self._active):
            result = score_symbol(self, symbol)
            if result is None or result["score"] < 6:
                continue

            cond_str = ",".join("T" if c else "F" for c in result["conditions"])
            self.log(
                f"SIGNAL|{date_str}|{symbol.value}|{result['rating']}|"
                f"{result['score']}/8|{cond_str}"
            )
            day_signals.append({
                "ticker": symbol.value,
                "score": result["score"],
                "rating": result["rating"],
                "conditions": result["conditions"],
            })

        self._signals[date_str] = day_signals
        self.log(f"AUDIT_SUMMARY|{date_str}|count={len(day_signals)}|universe={len(self._active)}")

    def on_end_of_algorithm(self) -> None:
        payload = json.dumps(self._signals)
        self.object_store.save("bct_signals", payload)
        self.log(f"BACKTEST_COMPLETE|signals_saved|dates={len(self._signals)}")
