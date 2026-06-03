from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext


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
