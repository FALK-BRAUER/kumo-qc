"""Regime phase: E121 VIX Ichimoku 2-tier capacity gate.

Kind: regime
Marker: vix_ichimoku_tier_v1
Tested params: enabled=True (champion-asis-v1; no overrides)
Charter: single code path, NEVER blocks (capacity-only). Faithful carve of oracle
_rebalance L470-480 (baseline-oracle-v0). VIX > cloud_top → tier 2 (unlimited
capacity). VIX <= cloud_top → tier 1 (fallback cap). Default fallback = 9999
(effectively unlimited either way for champion-asis-v1).
DO NOT modify evaluate() logic — breaks champion-asis-v1 parity (ARCH-C ±0.01 gate).

# FLAG: the source read `self._params.get("max_positions", 9999)` as the tier-1
# fallback cap. `max_positions` is a FORBIDDEN charter count-cap param, so it is NOT
# exposed as a Params field. The verbatim fallback constant (_MAX_POSITIONS_DEFAULT
# = 9999) is preserved — champion-asis-v1 never overrode it, so behavior is identical.
# The runtime slot cap genuinely comes from VIX tier (this output), not a config param.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext

_MAX_POSITIONS_DEFAULT = 9999  # tier-1 fallback (oracle default; never overridden in champion-asis-v1)


class VixIchimokuTier(BasePhase):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["vix_tier"]

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "VixIchimokuTier.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")

        regime_gate_enabled = getattr(qc, "regime_gate_enabled", True)
        vix = getattr(qc, "vix", None)
        vix_ichi = getattr(qc, "vix_ichi", None)

        max_positions = _MAX_POSITIONS_DEFAULT

        if not regime_gate_enabled or vix is None or vix_ichi is None or not vix_ichi.is_ready:
            # Regime gate disabled or indicators not ready — pass with unlimited capacity
            ctx.bar_state.phase_outputs.setdefault("vix_tier", []).append(
                {"max_positions": max_positions, "tier": 1}
            )
            return PhaseResult(
                decision="pass",
                blocked=False,
                reason="vix_ichimoku not ready or disabled",
                facts={"max_positions": max_positions},
                metrics={},
            )

        if not qc.securities.contains_key(vix):
            ctx.bar_state.phase_outputs.setdefault("vix_tier", []).append(
                {"max_positions": max_positions, "tier": 1}
            )
            return PhaseResult(decision="pass", blocked=False, reason="VIX not in securities", facts={}, metrics={})

        vix_price = float(qc.securities[vix].price)
        vix_cloud_top = max(
            vix_ichi.senkou_a.current.value,
            vix_ichi.senkou_b.current.value,
        )

        if vix_price > vix_cloud_top:
            tier = 2
            effective_max = 9999  # above VIX cloud = unlimited
        else:
            tier = 1
            effective_max = max_positions

        ctx.bar_state.phase_outputs.setdefault("vix_tier", []).append(
            {"max_positions": effective_max, "tier": tier}
        )

        return PhaseResult(
            decision=f"tier_{tier}",
            blocked=False,  # NEVER blocks — capacity only
            reason=f"VIX={vix_price:.2f} vs cloud_top={vix_cloud_top:.2f} → tier={tier}",
            facts={"vix": vix_price, "cloud_top": vix_cloud_top, "tier": tier, "max_positions": effective_max},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "vix_ichimoku_tier_v1"
