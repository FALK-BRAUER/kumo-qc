"""Exit phase: Rotation — free cash-locked slots for higher-conviction candidates (#339 RUN R).

Kind: exit_rotation · Clock: DAILY · Marker: rotation_v1

#339 finding: the combined-cloud champion is SLOT-LOCKED — winners hold the cloud-bottom trail, tie
up all cash (cash_ok=18 of 245 gap-eligible days → 217 entries blocked for lack of cash), so the
strategy can't act on fresh higher-conviction signals. Rotation breaks the lock: on the daily
decision, if cash is EXHAUSTED (can't fund a new position) AND a fresh candidate today out-scores the
WEAKEST held position by MARGIN AND that laggard is WEAKENING → FULL-exit the laggard (clean
FIRE_EXITS, cancels its protective stop — no GUARD-1 trim issue), freeing cash for the new name T+1.

Grounded in sT10e (142 rotation exits) + George's core (rotate dead money into fresh signals). NEVER
rotates a trending winner — the laggard must be weakening (below daily Tenkan OR dropped out of
today's signal winners = score decayed). Conservative: rotates AT MOST ONE position per decision
(the single weakest), and only when strictly out-scored — no churn.

Charter: single code path; blocked=False always (it only frees a slot, never blocks the chain).
Needs decision_score@entry (engine stamps it in _position_meta) + the daily snapshot winners
(qc._candidate_snapshot). Cold/missing data on the laggard → treat as NOT weakening (don't force a
rotation on incomplete info — rotation is opportunistic, not a protective stop).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext


class Rotation(BasePhase):
    PHASE_KIND = "exit_rotation"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        margin: float = 1.0          # new candidate must out-score the weakest held by > margin
        position_pct: float = 0.10   # a new position needs ~this fraction of equity → cash-exhausted test
        enabled: bool = True

    def __init__(self, params: "Rotation.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def _is_weakening(self, qc: Any, sym: Any, snap: dict[str, Any]) -> bool:
        """Laggard is weakening if it dropped OUT of today's signal winners (score decayed below the
        signal bar) OR daily close < daily Tenkan (momentum rolling over). Cold/missing d_ichi →
        rely on the snapshot-dropout signal only (no force-rotate on incomplete data)."""
        if sym not in snap:  # no longer a daily signal winner → decayed
            return True
        ind = getattr(qc, "_indicators", {}).get(sym)
        d_ichi = ind.get("d_ichi") if ind else None
        if d_ichi is None or not getattr(d_ichi, "is_ready", False):
            return False  # can't assess Tenkan; snapshot said it's still a winner → not weakening
        try:
            return float(qc.securities[sym].close) < float(d_ichi.tenkan.current.value)
        except Exception:  # noqa: BLE001 — missing security/price → don't force-rotate
            return False

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        pf = qc.portfolio
        total = float(pf.total_portfolio_value)
        cash = float(pf.cash)

        # cash AVAILABLE (a new position is fundable) → no lock to break → no rotation.
        if total <= 0 or cash >= self.p.position_pct * total:
            return PhaseResult(decision=[], blocked=False, reason="cash available — no rotation",
                               facts={"rotations": 0}, metrics={})

        meta = getattr(qc, "_position_meta", {})
        indicators = getattr(qc, "_indicators", {})
        held_scored = []
        for sym, holding in list(pf.items()):
            if not getattr(holding, "invested", False):
                continue
            # skip a delisted/unsubscribed held name (no live indicator) — not a rotation candidate
            # (liquidation/protective-stop handles it); also avoids a securities[] KeyError downstream.
            if indicators.get(sym) is None:
                continue
            m = meta.get(sym)
            sc = m.get("decision_score") if m else None
            if sc is not None:
                held_scored.append((sym, int(sc)))

        snap = getattr(qc, "_candidate_snapshot", {})
        held_syms = {s for s, _ in held_scored}
        new_cands = [(s, int(snap[s]["score"])) for s in snap
                     if s not in held_syms and snap[s].get("score") is not None]
        if not held_scored or not new_cands:
            return PhaseResult(decision=[], blocked=False,
                               reason=f"no rotation (held_scored={len(held_scored)}, new={len(new_cands)})",
                               facts={"rotations": 0}, metrics={})

        best_new_sym, best_new_score = max(new_cands, key=lambda x: x[1])
        worst_held_sym, worst_held_score = min(held_scored, key=lambda x: x[1])

        # margin = the MINIMUM score EDGE (points) the new candidate must beat the weakest held by.
        # Scores are integers (≤8) and the champion holds 7s while 8s appear → the realistic edge is
        # exactly 1 point; margin=1.0 with a strict `best > worst + margin` would need a 2-point edge
        # (impossible) → rotation never fires (verified: 8-vs-7 days). Use `edge >= margin` so a
        # ≥1-point edge fires (8 beats 7).
        rotations = 0
        edge = best_new_score - worst_held_score
        if edge >= self.p.margin and self._is_weakening(qc, worst_held_sym, snap):
            holding = pf[worst_held_sym]
            ctx.bar_state.exit_intents.append(
                OrderIntent(
                    ticker=worst_held_sym.value, qty=-holding.quantity,
                    price=float(qc.securities[worst_held_sym].close),
                    stop=0.0, module="exit.rotation", risk_dollars=0.0,
                    order_type="market",  # #386: market sell on slot-recycle (no implicit MOO)
                )
            )
            rotations = 1
            log = getattr(qc, "log", None)
            if callable(log):
                log(f"ROTATION|{date_str}|out={worst_held_sym.value}(score={worst_held_score})|"
                    f"in={best_new_sym.value}(score={best_new_score})|margin={self.p.margin}")

        return PhaseResult(
            decision=[worst_held_sym.value] if rotations else [],
            blocked=False,
            reason=f"{rotations} rotation(s)",
            facts={"rotations": rotations, "cash_exhausted": True,
                   "best_new_score": best_new_score, "worst_held_score": worst_held_score},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "rotation_v1"
