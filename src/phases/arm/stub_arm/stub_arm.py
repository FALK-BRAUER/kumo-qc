"""Arm phase: StubArm — the M1 DAY-clock arm module. Runs IN-CHAIN after regime (so it sees the
signal winners in bar_state.sized_orders AND the #277 regime block in bar_state.bar_blocked). Writes
the day-chain WINNERS into the framework carry qc._armed (keyed by the canonical _active Symbol):
{sym: {zone, daily_kijun, armed_date}}.

#386 STAGE-1 PARITY CONTRACT: this reproduces lean_entry._capture_candidate_snapshot byte-for-byte so
qc._armed == qc._candidate_snapshot (the live crash-on-divergence assertion proves the modular arm
reproduces the legacy daily decision before anything is deleted). That means, EXACTLY as the snapshot:
- winners = bar_state.sized_orders (the BCT signal winners), GATED to [] when bar_state.bar_blocked
  (#277 regime gate → zero intraday candidates that session);
- FRESH each daily decision (replace, NOT persist) — a name dropped from today's winners disappears;
- key by the SAME canonical _active Symbol (resolve via canonical_symbol_key, never Symbol.create);
- zone = securities[sym].price (== snapshot signal_price, the gap reference);
- daily_kijun = the maintained daily Ichimoku kijun (the thesis floor);
- SKIP a winner that is decided-but-not-subscribed (sym None) or has a cold daily Ichimoku
  (d_ichi not ready) — never arm a half-formed thesis.
The ZONE VALUE is strategy (this stub = enter near the signal price); the engine NEVER computes it —
it only persists/exposes/evicts the opaque blob. Real arm modules (Stage-2) compute pullback/breakout
zones + invalidation + the persist-until-fired lifecycle. NO qty here: sizing is INTRADAY at fire.

Kind: arm · Clock: DAILY · Marker: stub_arm_v2 (Stage-1 snapshot-parity).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key


class StubArm(BasePhase):
    PHASE_KIND = "arm"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []   # writes qc._armed (the carry), not bar_state

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "StubArm.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        # FRESH each daily decision (matches the snapshot's rebuild-fresh semantics).
        armed: dict[Any, dict[str, Any]] = {}
        qc._armed = armed
        # #277 regime gate: a blocked daily bar arms NOTHING (== snapshot winners=[]).
        if getattr(ctx.bar_state, "bar_blocked", False):
            return PhaseResult(decision=[], blocked=False,
                               reason="stub arm: regime-blocked → 0 armed (#277)",
                               facts={"added": 0, "armed_total": 0}, metrics={})
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        indicators = getattr(qc, "_indicators", {})
        date_str = ctx.time.strftime("%Y-%m-%d")
        for intent in ctx.bar_state.sized_orders:           # daily clock: signal winners
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                continue                                    # decided-but-not-subscribed → snapshot skips it
            ind = indicators.get(sym)
            d_ichi = ind.get("d_ichi") if ind else None
            if d_ichi is None or not getattr(d_ichi, "is_ready", False):
                continue                                    # cold daily thesis → never arm half-formed
            try:
                zone = float(qc.securities[sym].price)      # == snapshot signal_price (gap reference)
                daily_kijun = float(d_ichi.kijun.current.value)
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            armed[sym] = {"zone": zone, "daily_kijun": daily_kijun, "armed_date": date_str}
        return PhaseResult(decision=[], blocked=False,
                           reason=f"stub arm: {len(armed)} armed (snapshot-parity)",
                           facts={"added": len(armed), "armed_total": len(armed)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "stub_arm_v2"
