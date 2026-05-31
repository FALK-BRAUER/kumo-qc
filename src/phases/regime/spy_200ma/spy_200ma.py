"""Regime phase: SPY > 200-day SMA gate (E40b Phase2).

Kind: regime
Marker: spy_200ma_v1
Tested params: enabled=True (champion-asis-v1; no overrides)
Charter: single code path, exits run before this phase — no exit impact.
Blocks entries when SPY below 200MA. Faithful carve of oracle _rebalance L514-520
(baseline-oracle-v0).
DO NOT modify evaluate() logic — breaks champion-asis-v1 parity (ARCH-C ±0.01 gate).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class SpySma200(BasePhase):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "SpySma200.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")

        spy_sma200 = getattr(qc, "spy_sma200", None)
        spy = getattr(qc, "spy", None)
        # FAIL-LOUD GUARD (#261-7): a NOT-READY regime gate must BLOCK, never fail-OPEN.
        # Previously a cold/missing spy_sma200 returned blocked=False (PASS) → entries fired
        # UNGATED while the regime filter was cold (the fail-open mirage: the gate silently waves
        # everything through on partial state). The anti-mirage default is block-until-ready: a
        # not-ready regime gate cannot have approved the regime, so it must BLOCK entries until
        # warm — never silently pass. (Latent on the champion path: WARMUP_DAYS=560 ≫ the 200d
        # SMA, so the gate is warm before any live bar; this is a dormant defense-in-depth net.)
        if spy_sma200 is None or not spy_sma200.is_ready or spy is None:
            return PhaseResult(
                decision="block",
                blocked=True,
                reason="spy_sma200 not ready — BLOCK until warm (#261-7, fail-closed regime)",
                facts={"date": date_str, "regime_ready": False},
                metrics={},
            )

        spy_price = float(qc.securities[spy].price)
        spy_ma200 = float(spy_sma200.current.value)

        if spy_price < spy_ma200:
            return PhaseResult(
                decision="block",
                blocked=True,
                reason=f"SPY {spy_price:.2f} < MA200 {spy_ma200:.2f}",
                facts={"spy": spy_price, "ma200": spy_ma200, "date": date_str},
                metrics={},
            )

        return PhaseResult(
            decision="pass",
            blocked=False,
            reason=f"SPY {spy_price:.2f} >= MA200 {spy_ma200:.2f}",
            facts={"spy": spy_price, "ma200": spy_ma200},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "spy_200ma_v1"
