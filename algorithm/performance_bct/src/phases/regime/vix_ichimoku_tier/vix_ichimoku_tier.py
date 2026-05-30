"""
Regime phase: E121 VIX Ichimoku 2-tier capacity gate.
NOT a full block — reduces max_positions capacity. Exits never affected.
Faithful carve of oracle _rebalance L470-480 (baseline-oracle-v0).
VIX > cloud_top → tier 2 (unlimited capacity). VIX <= cloud_top → tier 1 (MAX_POSITIONS cap).
Default oracle MAX_POSITIONS = 9999 (effectively unlimited either way for champion-asis-v1).
"""
from __future__ import annotations
from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext


class VixIchimokuTier(PhaseInterface):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = ["vix_tier"]

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")

        regime_gate_enabled = getattr(qc, "regime_gate_enabled", True)
        vix = getattr(qc, "vix", None)
        vix_ichi = getattr(qc, "vix_ichi", None)

        max_positions = self._params.get("max_positions", 9999)

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
