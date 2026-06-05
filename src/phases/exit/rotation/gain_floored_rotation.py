"""Exit phase: GainFlooredRotation — the #345/#363 rotation tournament (gain-floored spine).

Kind: exit_rotation · Clock: DAILY · Marker: gain_floored_rotation_<variant>_v1

PRIOR (project_rotation_cuts_floor / #341 REJECTED): plain evict-weakest rotation HURT the bankable
floor — it evicts CONSOLIDATING-FROM-LOSS carriers (winners-in-waiting mid-base) and fights
let-winners-run. The ONE shape identified viable-but-never-validated = rotation-v2b GAIN-FLOORED.

SPINE (all variants): a held name is EVICTABLE only if it is in GAIN (close > entry_price). A
consolidating-from-loss carrier (close <= entry) is NEVER evicted — that is the teeth that protects
the floor against the #341 failure mode.

Variants (the tournament axis):
  R1 evict-on-better-candidate: at cash-exhausted (book ~at gross-cap) AND a new candidate out-scores
     the weakest GAIN-POSITIVE held by >= margin AND that laggard is weakening → FULL-exit it, free its
     capital for the new entry T+1.
  R2 lock-the-weakening-gain: FULL-exit the weakest GAIN-POSITIVE held that is weakening (below daily
     Tenkan OR dropped from the signal snapshot) — lock the gain before it round-trips. Pure cull, no
     cash/candidate gate (the "take the gain off the table" shape).
  R3 full-exit-redeploy: like R1, but ALSO emit an ADD to the STRONGEST existing held (redeploy the
     freed laggard capital into the best winner — controlled concentration). Uses the #378 add-path
     (gross-cap + stop-resize). FULL-exit (not a partial trim) → no #276a trim-guard.

FULL-exit only (FIRE_EXITS cancels the protective stop cleanly — no #276a trim-guard). At most ONE
eviction per daily decision (the single weakest gain-positive laggard) — conservative, no churn.
Cold/missing data on the laggard → NOT weakening / NOT evictable (rotation is opportunistic, never a
forced protective action).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext


class GainFlooredRotation(BasePhase):
    PHASE_KIND = "exit_rotation"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        variant: str = "R1"          # R1 / R2 / R3 (the tournament axis)
        margin: float = 1.0          # new candidate must out-score the weakest GAIN held by >= margin (R1/R3)
        position_pct: float = 0.10   # a new position needs ~this fraction of equity → cash-exhausted test (R1/R3)
        redeploy_pct: float = 0.05    # R3: add this fraction of equity to the strongest held on redeploy
        enabled: bool = True

    def __init__(self, params: "GainFlooredRotation.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    # ── helpers ──
    def _in_gain(self, qc: Any, sym: Any, meta: dict[str, Any]) -> bool:
        """The GAIN-FLOOR spine: evictable only if close > entry_price (in profit). A consolidating-
        from-loss carrier (close <= entry) is protected (the #341 failure mode the floor prevents)."""
        m = meta.get(sym)
        if not m or "entry_price" not in m:
            return False
        try:
            return float(qc.securities[sym].close) > float(m["entry_price"]) > 0.0
        except (KeyError, AttributeError, TypeError, ValueError):
            return False

    def _is_weakening(self, qc: Any, sym: Any, snap: dict[str, Any]) -> bool:
        """Weakening = dropped from today's signal snapshot (score decayed) OR close < daily Tenkan.
        Cold/missing d_ichi → rely on snapshot-dropout only (no force-rotate on incomplete data)."""
        if sym not in snap:
            return True
        ind = getattr(qc, "_indicators", {}).get(sym)
        d_ichi = ind.get("d_ichi") if ind else None
        if d_ichi is None or not getattr(d_ichi, "is_ready", False):
            return False
        try:
            return float(qc.securities[sym].close) < float(d_ichi.tenkan.current.value)
        except (KeyError, AttributeError, TypeError, ValueError):
            return False

    def _gain_positive_held(self, qc: Any, pf: Any, meta: dict, indicators: dict) -> list[tuple]:
        """Held names that are invested, have a live indicator + a decision_score, AND are in GAIN
        (the floor). Returns [(sym, score)]."""
        out = []
        for sym, holding in list(pf.items()):
            if not getattr(holding, "invested", False) or indicators.get(sym) is None:
                continue
            if not self._in_gain(qc, sym, meta):
                continue  # gain-floor: never evict a consolidating-from-loss carrier
            m = meta.get(sym)
            sc = m.get("decision_score") if m else None
            if sc is not None:
                out.append((sym, int(sc)))
        return out

    def _emit_exit(self, qc: Any, ctx: PhaseContext, sym: Any) -> None:
        ctx.bar_state.exit_intents.append(OrderIntent(
            ticker=sym.value, qty=-qc.portfolio[sym].quantity,
            price=float(qc.securities[sym].close), stop=0.0, module="exit.gain_floored_rotation",
            risk_dollars=0.0,
        ))

    # ── decision ──
    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        pf = qc.portfolio
        total = float(pf.total_portfolio_value)
        meta = getattr(qc, "_position_meta", {})
        indicators = getattr(qc, "_indicators", {})
        snap = getattr(qc, "_candidate_snapshot", {})
        variant = self.p.variant
        gain_held = self._gain_positive_held(qc, pf, meta, indicators)
        evicted = None

        if not gain_held:
            return PhaseResult(decision=[], blocked=False, reason="no gain-positive held — gain-floor holds",
                               facts={"rotations": 0}, metrics={})

        if variant == "R2":
            # lock-the-weakening-gain: evict the WEAKEST gain-positive held that's weakening. No
            # cash/candidate gate. At most one (the single weakest weakening gainer).
            weakening = [(s, sc) for s, sc in gain_held if self._is_weakening(qc, s, snap)]
            if weakening:
                evicted, esc = min(weakening, key=lambda x: x[1])
                self._emit_exit(qc, ctx, evicted)
                _log(qc, f"ROTATION_R2|{date_str}|lock-gain out={evicted.value}(score={esc}) weakening")
        else:
            # R1 / R3: cash-exhausted + a new candidate strictly out-scores the weakest gain held.
            cash = float(pf.cash)
            if total <= 0 or cash >= self.p.position_pct * total:
                return PhaseResult(decision=[], blocked=False, reason="cash available — no rotation",
                                   facts={"rotations": 0}, metrics={})
            held_syms = {s for s, _ in gain_held}
            new_cands = [(s, int(snap[s]["score"])) for s in snap
                         if s not in held_syms and snap[s].get("score") is not None]
            if not new_cands:
                return PhaseResult(decision=[], blocked=False, reason="no new candidate — no rotation",
                                   facts={"rotations": 0}, metrics={})
            best_new_sym, best_new_score = max(new_cands, key=lambda x: x[1])
            worst_sym, worst_score = min(gain_held, key=lambda x: x[1])
            if best_new_score - worst_score >= self.p.margin and self._is_weakening(qc, worst_sym, snap):
                evicted = worst_sym
                self._emit_exit(qc, ctx, evicted)
                _log(qc, f"ROTATION_{variant}|{date_str}|out={worst_sym.value}(score={worst_score})|"
                          f"in={best_new_sym.value}(score={best_new_score})")
                if variant == "R3":
                    # redeploy the freed capital into the STRONGEST existing held (an ADD via #378).
                    strongest = max((g for g in gain_held if g[0] != evicted), key=lambda x: x[1], default=None)
                    if strongest is not None:
                        st_sym = strongest[0]
                        st_close = float(qc.securities[st_sym].close)
                        qty = int((self.p.redeploy_pct * total) / st_close) if st_close > 0 else 0
                        if qty >= 1:
                            ctx.bar_state.add_intents.append(OrderIntent(
                                ticker=st_sym.value, qty=qty, price=st_close, stop=0.0,
                                module="exit.gain_floored_rotation.redeploy",
                                risk_dollars=float(self.p.redeploy_pct * total),
                            ))
                            _log(qc, f"ROTATION_R3_REDEPLOY|{date_str}|add={st_sym.value} qty={qty}")

        return PhaseResult(
            decision=[evicted.value] if evicted else [], blocked=False,
            reason=f"{1 if evicted else 0} gain-floored rotation(s) [{variant}]",
            facts={"rotations": 1 if evicted else 0, "gain_held": len(gain_held)}, metrics={},
        )

    @property
    def version_marker(self) -> str:
        return f"gain_floored_rotation_{self.p.variant}_v1"


def _log(qc: Any, msg: str) -> None:
    log = getattr(qc, "log", None)
    if callable(log):
        log(msg)
