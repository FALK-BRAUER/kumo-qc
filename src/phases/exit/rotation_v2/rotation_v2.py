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
        # #364 tournament levers (ALL default to the #339 rotation_v2 baseline behaviour = R1-A-as-was):
        evict_select: str = "score"  # which stalled-green to evict: "score" (lowest decision_score@entry,
                                     # the #339 default) | "momentum" (weakest momentum = furthest below
                                     # Tenkan as % of price — HQ R1-A spec).
        adx_falling_gate: bool = False  # R1-B: evict-candidate ALSO needs ADX falling (adx_now < adx_3back)
                                        # → only evict stalled-AND-decelerating (not a consolidating winner).
        no_new_high_days: int = 0       # R1-C: >0 → evict-candidate ALSO needs NO new high in N days
                                        # (close < max(daily highs, last N)); 0 = gate off.
        gain_floor_pct: float = 0.0     # R1-D: >0 → evict-candidate ALSO needs unrealized gain% >= this
                                        # (bank MEANINGFUL gains, don't churn tiny ones); 0 = gate off.
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
        # #364 R1-D gain-floor: only bank MEANINGFUL gains — a tiny gain isn't worth a slot recycle.
        if self.p.gain_floor_pct > 0.0:
            if (close - entry_px) / entry_px < self.p.gain_floor_pct:
                return False  # gain below floor → PROTECTED (don't churn it)
        # #364 R1-B ADX-falling: only evict stalled-AND-DECELERATING (don't evict a consolidating
        # winner whose ADX is still rising — it may resume). adx_window[0]=now, [3]=3 bars back.
        if self.p.adx_falling_gate:
            aw = (ind or {}).get("adx_window")
            if aw is None or getattr(aw, "count", 0) < 4:
                return False  # can't assess ADX slope → protected
            if not (float(aw[0]) < float(aw[3])):
                return False  # ADX rising/flat → not decelerating → protected
        # #364 R1-C no-new-high: only evict stalled-AND-not-recently-making-highs. Reads the optional
        # high_window (RollingWindow of recent daily highs); absent → conservative (protected).
        if self.p.no_new_high_days > 0:
            hw = (ind or {}).get("high_window")
            if hw is None or getattr(hw, "count", 0) < self.p.no_new_high_days:
                return False  # no window / not enough history → can't assess → protected
            recent_high = max(float(hw[i]) for i in range(self.p.no_new_high_days))
            if close >= recent_high:
                return False  # made a new N-day high → still active → protected
        return True  # PnL>0 + below Tenkan + above Kijun (+ gates) = stalled green → EVICTABLE

    def _momentum_gap(self, qc: Any, sym: Any) -> float:
        """(Tenkan − close)/close for a stalled-green name (called only after _is_stalled_green, so
        close<Tenkan → gap>0). Larger = weaker momentum (furthest below Tenkan). 0.0 if unavailable."""
        try:
            close = float(qc.securities[sym].close)
            d_ichi = qc._indicators[sym]["d_ichi"]
            tenkan = float(d_ichi.tenkan.current.value)
            if close > 0.0:
                return (tenkan - close) / close
        except Exception:  # noqa: BLE001
            pass
        return 0.0

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
        # ONE pass over pf.items() (LEAN's Portfolio yields KeyValuePairs — never `for s in pf` +
        # pf[s], that get_Item-fails on the KVP). Collect held_syms + the stalled-green evictable pool.
        evictable = []
        held_syms = set()
        for sym, holding in list(pf.items()):
            if not getattr(holding, "invested", False):
                continue
            held_syms.add(sym)
            if indicators.get(sym) is None:
                continue
            m = meta.get(sym)
            sc = m.get("decision_score") if m else None
            if sc is None:
                continue
            if self._is_stalled_green(qc, sym, ctx.time):
                # momentum_gap = (Tenkan − close)/close: how far BELOW Tenkan as % of price. Larger =
                # weaker momentum (more stalled). The evict_select="momentum" tiebreaker (HQ R1 spec).
                evictable.append((sym, int(sc), self._momentum_gap(qc, sym)))

        snap = getattr(qc, "_candidate_snapshot", {})
        new_cands = [(s, int(snap[s]["score"])) for s in snap
                     if s not in held_syms and snap[s].get("score") is not None]
        if not evictable or not new_cands:
            return PhaseResult(decision=[], blocked=False,
                               reason=f"no rotation (stalled-green evictable={len(evictable)}, new={len(new_cands)})",
                               facts={"rotations": 0, "evictable": len(evictable)}, metrics={})

        best_new_sym, best_new_score = max(new_cands, key=lambda x: x[1])
        # SELECT which stalled-green to evict. "momentum" (HQ R1) = WEAKEST momentum (max gap below
        # Tenkan). "score" (#339 default) = lowest decision_score@entry. The score-edge TRIGGER still
        # gates the selected target (a fresh signal must out-score it by >= margin).
        if self.p.evict_select == "momentum":
            worst_held_sym, worst_held_score, _gap = max(evictable, key=lambda x: x[2])
        else:
            worst_held_sym, worst_held_score, _gap = min(evictable, key=lambda x: x[1])

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
