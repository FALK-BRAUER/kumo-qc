"""Regime phase: MarketBreadthGate (#254 catalog, #386 scenario A/C).

Eligible-to-open ONLY when > THRESHOLD% of the S&P constituents are above their 200-day MA (breadth).
Below threshold → BLOCK new longs (a risk-off breadth regime). Param: pct_threshold (A=0.50, C=0.40).

Reads qc.breadth_pct_above_200ma (the runtime maintains it; 0..1). FAIL-CLOSED (#261-7): a not-ready /
missing breadth value BLOCKS (a cold regime gate never fail-opens). Kind: regime · Marker: market_breadth_gate_v1.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class MarketBreadthGate(BasePhase):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        pct_threshold: float = 0.50  # >50% of S&P >200MA to open (A); 0.40 for C
        enabled: bool = True

    def __init__(self, params: "MarketBreadthGate.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        breadth = getattr(qc, "breadth_pct_above_200ma", None)
        # FAIL-CLOSED: cold/missing breadth → BLOCK (never fire ungated on partial state, #261-7).
        if breadth is None:
            return PhaseResult(decision="block", blocked=True,
                               reason="breadth not ready — BLOCK until warm (fail-closed regime)",
                               facts={"date": date_str, "regime_ready": False}, metrics={})
        breadth = float(breadth)
        if breadth <= self.p.pct_threshold:
            return PhaseResult(decision="block", blocked=True,
                               reason=f"breadth {breadth:.2%} <= {self.p.pct_threshold:.0%} — risk-off, no new longs",
                               facts={"breadth": breadth, "threshold": self.p.pct_threshold, "date": date_str}, metrics={})
        return PhaseResult(decision="pass", blocked=False,
                           reason=f"breadth {breadth:.2%} > {self.p.pct_threshold:.0%}",
                           facts={"breadth": breadth, "threshold": self.p.pct_threshold}, metrics={})

    @property
    def version_marker(self) -> str:
        return "market_breadth_gate_v1"
