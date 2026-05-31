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

#243 extends this (charting-ONLY, NO trading effect, config_hash UNCHANGED — no new Param):
  - Regime/spy_close + Regime/spy_ma200: the #265 regime-timing mechanism (SPY-MA200 cross).
  - Signal/n_qualifying: the daily count that scored >= min_score (len sized_orders).
  - Score/<ticker>: per-name maintained-indicator scores for a FIXED probe set of the #265
    divergent names (module constant _SCORE_PROBES). -1.0 sentinel = not selectable.
These make cloud's maintained-indicator VALUES observable so #268 can diff cloud-vs-local
and root-cause the signal residual (#265: same RAW prices, divergent maintained VALUES).

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
from phases.shared.oracle_helpers import score_symbol_native

# #243: FIXED probe set of the #265 cloud-vs-local divergent names. A MODULE CONSTANT (NOT a
# Param) on purpose — config_hash derives from StrategyConfig slots/impl/params, so adding a
# Param would bump the champion pin e573e84b1ce1. These names are recomputed read-only in
# diagnostics (the signal phase already scored + discarded them) purely to make cloud's
# maintained-indicator score VALUES observable; zero trading effect. -1.0 = "not selectable"
# (not subscribed / indicators not ready) — distinguishes that from a real score of 0.
_SCORE_PROBES = ("DRI", "CME", "AMZN", "COST", "CRWD", "KGC")


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

        # #243: extended observability (charting-ONLY, inert). #268 diffs cloud-vs-local on:
        #   Regime/spy_close + spy_ma200 — the #265 regime-timing mechanism (SPY-MA200 cross).
        #   Signal/n_qualifying — the daily scoring-breadth count (sized_orders is populated;
        #     diagnostics runs AFTER signal).
        #   Score/<ticker> — per-name maintained-indicator scores for the divergent probe set.
        # Each block is guarded so a FakeQC / not-ready state degrades gracefully (single code
        # path, no `if cloud`). Recomputing scores here is pure read-only observability — the
        # signal phase already computed + discarded them; this NEVER touches sized_orders.
        n_qualifying = -1
        regime_charted = False
        probe_scores: dict[str, float] = {}
        if callable(plot):
            # 1. Regime — exactly as spy_200ma.py reads it. Skip (don't plot a misleading 0)
            #    when the SMA is cold/None or SPY is unsubscribed.
            spy = getattr(qc, "spy", None)
            spy_sma200 = getattr(qc, "spy_sma200", None)
            if spy is not None and spy_sma200 is not None and getattr(spy_sma200, "is_ready", False):
                try:
                    spy_close = float(qc.securities[spy].price)
                    spy_ma200 = float(spy_sma200.current.value)
                except (KeyError, AttributeError, TypeError, ValueError):
                    pass
                else:
                    plot("Regime", "spy_close", spy_close)
                    plot("Regime", "spy_ma200", spy_ma200)
                    regime_charted = True

            # 2. Signal breadth — the daily count that scored >= min_score (sized_orders).
            n_qualifying = len(ctx.bar_state.sized_orders)
            plot("Signal", "n_qualifying", n_qualifying)

            # 3. Per-name probe scores — resolve each probe ticker to a subscribed symbol and
            #    recompute its maintained-indicator score (read-only). -1.0 sentinel when the
            #    name is not active / its indicators are not ready / scorer returns None.
            active_by_value = {s.value: s for s in getattr(qc, "_active", set())}
            indicators = getattr(qc, "_indicators", {})
            for ticker in _SCORE_PROBES:
                score = -1.0
                symbol = active_by_value.get(ticker)
                if symbol is not None:
                    ind = indicators.get(symbol)
                    if ind is not None:
                        try:
                            result = score_symbol_native(qc, symbol, ind)
                        except (KeyError, AttributeError, TypeError, ValueError):
                            result = None
                        if result is not None:
                            score = float(result["score"])
                plot("Score", ticker, score)
                probe_scores[ticker] = score

        return PhaseResult(
            decision="charted",
            blocked=False,
            reason="universe counts + regime + signal breadth + probe scores emitted as chart series",
            facts={
                "active_set": active_set,
                "ranked": ranked,
                "n_qualifying": n_qualifying,
                "regime_charted": regime_charted,
                "probe_scores": probe_scores,
            },
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "chart_emit_v1"
