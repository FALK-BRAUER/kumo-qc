"""Diagnostics phase: cloud-observable universe counts via self.plot().

Kind: diagnostics
Marker: chart_emit_v1
Tested params: enabled=True, chart_name="Universe" (champion-asis; no overrides)
Charter: single code path — the plot runs IDENTICALLY local + cloud (locally LEAN
records the chart too; harmless). NO `if cloud` branch. Charting is pure observability
with ZERO trading effect: it reads runtime state + bar_state and emits numeric chart
series, never mutates LEAN.

Why this exists: QC's API no longer returns user Log() output and ObjectStore export is
blocked (non-Institutional), so cloud backtest internals are observable ONLY via custom
CHART series. This phase replaces an uncommitted main.py instrumentation hack with a
git-clean, committed phase. Emits the daily selected-universe size (the parity signal —
the Step-A 1.10x vendor residual was measured on THIS count) + the per-bar tracked
candidate count, so the cloud diff-ladder is observable WITHOUT instrumenting main.py.

QC plot API (verified via Context7 — /quantconnect/documentation):
  self.plot("<chartName>", "<seriesName>", value)  # snake_case Python wrapper; C# = Plot()
  - chart + series auto-create; numeric value plotted at the algorithm time (x = QC.Time).
  - Custom-chart numeric series surface via the REST endpoint POST /backtests/chart/read
    (ReadChartResponse.chart.series[].values — ascending time order). 4,000 pts/series cap.
  Sources:
    03 Writing Algorithms/01 Key Concepts/14 Debugging Tools/04 Charts.html (self.plot)
    01 Cloud Platform/99 API Reference/05 Backtest Management/02 Read Backtest/02 Charts
      (GET/POST /backtests/chart/read → ReadChartResponse)

qc.plot is REQUIRED on the QCAlgorithm contract (LEAN provides it). The call is
getattr-guarded so a unit-test FakeQC that lacks plot is a graceful no-op (no
AttributeError) rather than a crash — the guard is for test fakes, not an `if cloud`.

DO NOT add trading effect here. Charting only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class ChartEmit(BasePhase):
    PHASE_KIND = "diagnostics"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        enabled: bool = True
        chart_name: str = "Universe"

    def __init__(self, params: "ChartEmit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc

        # active-set count = the daily selected-universe size (THE parity signal; the
        # Step-A 1.10x vendor residual was measured on this count). Read defensively:
        # missing attr or None -> 0.
        active_set = len(getattr(qc, "_ranked_today", None) or [])
        # ranked-candidates = the per-bar tracked-candidate count from the universe phase.
        ranked = len(ctx.bar_state.ranked_candidates)

        # Emit numeric chart series. getattr-guard so a FakeQC without plot no-ops (tests);
        # LEAN always provides plot, so live/cloud always charts. Single code path — no
        # `if cloud`. plot(chart, series, value); chart+series auto-create at QC.Time.
        plot = getattr(qc, "plot", None)
        if callable(plot):
            plot(self.p.chart_name, "active_set", active_set)
            plot(self.p.chart_name, "ranked", ranked)

        return PhaseResult(
            decision="charted",
            blocked=False,
            reason="universe counts emitted as chart series",
            facts={"active_set": active_set, "ranked": ranked},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "chart_emit_v1"
