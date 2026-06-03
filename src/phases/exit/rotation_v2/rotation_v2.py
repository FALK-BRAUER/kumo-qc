"""Exit phase: RotationV2 — recycle DEAD-GREEN money, never book a loss or dump a runner (#339).

Kind: exit_rotation · Clock: DAILY · Marker: rotation_v2_v1

RUN R (rotation v1) HURT (-22.8% realized) because it evicted the weakest-WEAKENING (often UNDERWATER)
laggard → booked recoverable dips. WRONG END. Falk's corrected target (coherent with let-winners-run):
rotation recycles POSITIVE-BUT-FLAT names — gains that have stopped compounding and just occupy a slot.
Clean division of labour:
  - Trending winners (above Tenkan) → the TRAIL handles (let compound) — PROTECTED, never rotate.
  - Underwater names (PnL <= 0) → the STOPS handle (cut/recover to stop) — PROTECTED, rotation NEVER books a loss.
  - Positive-but-FLAT (PnL > 0, below Tenkan, above Kijun) → ROTATION recycles: bank the gain, free the slot.

EVICTABLE  = PnL > 0  AND  close < daily Tenkan (lost short-term momentum)  AND  close > daily Kijun
             (structure intact, not broken).
PROTECTED  = above Tenkan (trending) OR PnL <= 0 (underwater) OR <= Kijun (broken) OR d_ichi cold.
TRIGGER    = cash-exhausted AND a fresh snapshot winner out-scores the most-stalled evictable-green by
             >= margin → full-exit it (clean FIRE_EXITS), freeing cash for the fresh signal T+1.
min_hold_days = TUNABLE (default 0 — NOT a fixed 15; the '15' in the source was a config/hardcode bug).

assert-engaged (the whole point): every evicted name has PnL > 0 AND below-Tenkan AND above-Kijun;
ZERO underwater rotated; ZERO above-Tenkan (trending) rotated. Headline = floor-proxy vs S1 +21.13%.

blocked=False always. Needs decision_score@entry + entry_price (engine stamps both in _position_meta)
+ the daily snapshot winners (qc._candidate_snapshot).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext


class RotationV2(BasePhase):
    PHASE_KIND = "exit_rotation"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        margin: float = 1.0          # fresh candidate must out-score the stalled-green held by >= this edge
        position_pct: float = 0.10   # cash-exhausted test (< this fraction of equity free → locked)
        min_hold_days: int = 0       # TUNABLE: skip names held fewer than this (default 0 — never a fixed 15)
        enabled: bool = True

    def __init__(self, params: "RotationV2.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def _is_stalled_green(self, qc: Any, sym: Any, ctx_time: Any) -> bool:
        """EVICTABLE iff PnL>0 AND below Tenkan AND above Kijun (a gain that stopped compounding but
        isn't broken). Everything else PROTECTED: trending (>=Tenkan), underwater (<=entry), broken
        (<=Kijun), cold d_ichi, or too-fresh (min_hold). Conservative: any missing data → protected."""
        meta = getattr(qc, "_position_meta", {}).get(sym)
        if meta is None:
            return False
        try:
            close = float(qc.securities[sym].close)
        except Exception:  # noqa: BLE001
            return False
        entry_px = float(meta.get("entry_price", 0.0) or 0.0)
        if entry_px <= 0.0 or close <= entry_px:
            return False  # underwater / no entry ref → PROTECTED (stops handle; never book a loss)
        ind = getattr(qc, "_indicators", {}).get(sym)
        d_ichi = ind.get("d_ichi") if ind else None
        if d_ichi is None or not getattr(d_ichi, "is_ready", False):
            return False  # can't assess momentum → protected
        try:
            tenkan = float(d_ichi.tenkan.current.value)
            kijun = float(d_ichi.kijun.current.value)
        except Exception:  # noqa: BLE001
            return False
        if close >= tenkan:
            return False  # trending → the trail handles it, never rotate a runner
        if close <= kijun:
            return False  # broken structure → the stops handle it
        if self.p.min_hold_days > 0 and meta.get("entry_date") is not None:
            try:
                if (ctx_time - meta["entry_date"]).days < self.p.min_hold_days:
                    return False
            except Exception:  # noqa: BLE001
                pass
        return True  # PnL>0 + below Tenkan + above Kijun = stalled green → EVICTABLE

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        pf = qc.portfolio
        total = float(pf.total_portfolio_value)
        cash = float(pf.cash)
        if total <= 0 or cash >= self.p.position_pct * total:
            return PhaseResult(decision=[], blocked=False, reason="cash available — no rotation",
                               facts={"rotations": 0}, metrics={})

        meta = getattr(qc, "_position_meta", {})
        indicators = getattr(qc, "_indicators", {})
        # EVICTABLE pool = stalled-green held names only (with a decision_score to rank).
        evictable = []
        for sym, holding in list(pf.items()):
            if not getattr(holding, "invested", False) or indicators.get(sym) is None:
                continue
            m = meta.get(sym)
            sc = m.get("decision_score") if m else None
            if sc is None:
                continue
            if self._is_stalled_green(qc, sym, ctx.time):
                evictable.append((sym, int(sc)))

        held_syms = {s for s, _ in [(s, 0) for s in pf if getattr(pf[s], "invested", False)]}
        snap = getattr(qc, "_candidate_snapshot", {})
        new_cands = [(s, int(snap[s]["score"])) for s in snap
                     if s not in held_syms and snap[s].get("score") is not None]
        if not evictable or not new_cands:
            return PhaseResult(decision=[], blocked=False,
                               reason=f"no rotation (stalled-green evictable={len(evictable)}, new={len(new_cands)})",
                               facts={"rotations": 0, "evictable": len(evictable)}, metrics={})

        best_new_sym, best_new_score = max(new_cands, key=lambda x: x[1])
        # evict the MOST-STALLED green = lowest decision_score among the evictable-green pool.
        worst_held_sym, worst_held_score = min(evictable, key=lambda x: x[1])

        rotations = 0
        if best_new_score - worst_held_score >= self.p.margin:
            holding = pf[worst_held_sym]
            ctx.bar_state.exit_intents.append(
                OrderIntent(
                    ticker=worst_held_sym.value, qty=-holding.quantity,
                    price=float(qc.securities[worst_held_sym].close),
                    stop=0.0, module="exit.rotation_v2", risk_dollars=0.0,
                )
            )
            rotations = 1
            log = getattr(qc, "log", None)
            if callable(log):
                log(f"ROTATION_V2|{date_str}|out={worst_held_sym.value}(score={worst_held_score},stalled-green)|"
                    f"in={best_new_sym.value}(score={best_new_score})")

        return PhaseResult(
            decision=[worst_held_sym.value] if rotations else [],
            blocked=False,
            reason=f"{rotations} rotation(s); {len(evictable)} stalled-green evictable",
            facts={"rotations": rotations, "evictable": len(evictable),
                   "best_new_score": best_new_score, "worst_held_score": worst_held_score},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "rotation_v2_v1"
