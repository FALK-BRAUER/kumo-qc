"""Sizing phase: score-driven tier sizing COMPOSED WITH the committed-cash heat-cap.

Kind: sizing
Marker: score_tier_heatcap_v1
Tested params: position_pct=0.10, full=1.0, three_quarter=0.75, half=0.50, min_score=2
  (methodology-canonical defaults).
Sweep space (space()): position_pct x full x three_quarter x half x min_score — the genuinely
  sweepable axes (grid 3^5 = 243).
Complexity (COMPLEXITY): 5 free params (the five swept axes).

METHODOLOGY (the bible — strategy/methodology.md §4 SIZING TIERS; authoritative spec pinned in
GH#253). The entry-confirm phase (entry_selection/bct_entry_confirm) scores each candidate X/4
on the §2 components (C1 regime, C2 T-Bounce, C3 MACD, C4 volume) and PUBLISHES that int score
on `qc._entry_confirm[ticker]`. flat_pct_heatcap IGNORES that score (flat position_pct for every
name). THIS phase makes the X/4 BIND — the methodology sizing tiers:

    4/4 -> FULL    (full   x position_pct, default 1.00 x 0.10 = 10.0% of portfolio value)
    3/4 -> 75%     (three_quarter x position_pct, default 0.75 x 0.10 = 7.5%)
    2/4 -> 50%     (half  x position_pct, default 0.50 x 0.10 = 5.0%)
    <2  -> NO ENTRY (tier 0.0 — the candidate is not sized; a <2/4 name should already have been
                     GATED OUT upstream by bct_entry_confirm's min_confirm, so 0 here is defensive)

The tier multiplier sets the PER-NAME target (tier x position_pct x portfolio value); the gross
committed-cash heat-cap (carried verbatim from flat_pct_heatcap) then BOUNDS total exposure —
ranked candidates fill at their tier target until cash is exhausted (oracle breaks, not continues).
Composition: tier sets the per-name size, heat-cap bounds the total. A 4/4 name claims more
capital than a 2/4 name; both are capped by available cash.

MISSING-SCORE EDGE (FLAGGED — the contract decision):
  A candidate with NO `qc._entry_confirm` entry means the entry-confirm phase did not run / was
  not wired upstream (a broken phase stack — score sizing is meaningless without the scorer). We
  DECLINE such a candidate (tier 0.0 = no entry), NOT fall back to flat sizing. Rationale: this
  phase's CONTRACT is "size by the published X/4". Silently sizing an UNSCORED name at full size
  would (a) hide a wiring bug behind plausible P&L, and (b) violate the single-source charter
  (the score is the authority; absence of a score is absence of authority to enter). A wiring bug
  must FAIL VISIBLY (zero entries, liveness CI #251 catches orders==0) rather than masquerade as
  flat_pct_heatcap. If the WHOLE dict is absent (no entry_confirm phase at all), every candidate
  declines -> zero orders -> the build's liveness gate trips. That is the intended loud failure.

CHARTER: single code path (local == cloud); the heat-cap is a % gross-exposure rule (KEPT); NO
count caps / time exits / fixed slots. The tier fractions are PARAMS (methodology-canonical
defaults) so the methodology tier curve is sweepable without forking the impl.

No relative-path reads; no per-bar history; reads only qc.portfolio / qc.securities / qc._active /
qc._entry_confirm and ctx.bar_state.sized_orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.symbol_key import canonical_symbol_key
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace


class ScoreTierHeatcap(BasePhase):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal", "entry_selection"]  # needs the published X/4 score
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    # ADR D5 overfitting-defense: 5 swept axes (== space() axes).
    COMPLEXITY = ComplexityDecl(
        free_params=5,
        note="position_pct + full + three_quarter + half + min_score (the methodology tier curve).",
    )

    @dataclass(slots=True)
    class Params:
        position_pct: float = 0.10        # the FULL-tier base (4/4 = full x position_pct of PV)
        full: float = 1.00               # 4/4 tier multiplier (methodology: full size)
        three_quarter: float = 0.75      # 3/4 tier multiplier (methodology: 75%)
        half: float = 0.50               # 2/4 tier multiplier (methodology: 50%)
        min_score: int = 2               # minimum X/4 to ENTER (<2 -> tier 0.0, no entry)
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axes of the score-tier sizer (ADR D2). 5 axes -> grid 3^5 = 243.

            position_pct: the FULL-tier base size (the 4/4 fraction of portfolio value; 3/4 and
              2/4 scale down from it via the tier multipliers).
            full / three_quarter / half: the methodology tier curve (4/4 . 3/4 . 2/4). Default
              1.00/0.75/0.50 is the canonical curve; the sweep lets the curve steepen/flatten
              (e.g. a steeper 1.0/0.6/0.3 concentrates into 4/4 names) without forking the impl.
            min_score: the entry floor (2 canonical = enter >=2/4; 3 = enter only 3/4+; the <min
              tier is always 0.0 = no entry — a name below the floor is not sized).
            """
            return ParamSpace(
                axes={
                    "position_pct": (0.05, 0.10, 0.15),
                    "full": (1.00, 0.90, 0.80),
                    "three_quarter": (0.75, 0.66, 0.60),
                    "half": (0.50, 0.40, 0.33),
                    "min_score": (2, 3, 4),
                }
            )

    def __init__(self, params: "ScoreTierHeatcap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def _tier(self, score: int) -> float:
        """Map the published X/4 entry-confirm score to a tier multiplier (the methodology curve).

        4/4 -> full ; 3/4 -> three_quarter ; 2/4 -> half ; below min_score -> 0.0 (no entry).
        Scores above 4 (should never happen — the gate is X/4) clamp to the full tier.
        """
        p = self.p
        if score < p.min_score:
            return 0.0
        if score >= 4:
            return p.full
        if score == 3:
            return p.three_quarter
        if score == 2:
            return p.half
        # 0 or 1 but somehow >= min_score (min_score<2): treat as below the methodology floor.
        return 0.0

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        position_pct = self.p.position_pct

        # The single source of the X/4 score (published by entry_selection/bct_entry_confirm).
        # Case-insensitive lookup keyed on the canonical ticker (mirrors dv_rank_cap / signal).
        raw_scores = getattr(qc, "_entry_confirm", None)
        scores_by_lower: dict[str, int] = {}
        if isinstance(raw_scores, dict):
            scores_by_lower = {str(k).lower(): int(v) for k, v in raw_scores.items()}

        # Heat-cap (cash) only — no slot count. Fill ranked candidates at their TIER target
        # until cash is exhausted (oracle breaks, not continues — verbatim from flat_pct_heatcap).
        committed_cash = 0.0
        available_cash = float(qc.portfolio.cash)
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}  # #276b-1 FIX3
        filled: list[OrderIntent] = []
        skipped_cash = 0
        declined_score = 0   # <min_score tier 0.0 (defensive — should be gated upstream)
        declined_missing = 0  # no published score (broken stack — DECLINE, do not flat-fall-back)

        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                continue

            key = intent.ticker.lower()
            if key not in scores_by_lower:
                # No published X/4 for this name -> the entry-confirm phase didn't score it
                # (wiring bug). CONTRACT: decline, never fall back to flat sizing (FLAGGED).
                declined_missing += 1
                continue

            tier = self._tier(scores_by_lower[key])
            if tier <= 0.0:
                declined_score += 1
                continue

            try:
                price = float(qc.securities[sym].price)
            except Exception:
                continue
            if price <= 0:
                continue

            # Tier sets the PER-NAME target; the heat-cap then bounds total gross exposure.
            target_value = float(qc.portfolio.total_portfolio_value) * position_pct * tier
            if available_cash - committed_cash < target_value:
                skipped_cash += 1
                break  # cash exhausted (oracle breaks, not continues)

            quantity = int(target_value / price)
            if quantity <= 0:
                continue

            committed_cash += target_value
            filled.append(OrderIntent(
                ticker=intent.ticker,
                qty=quantity,
                price=price,
                stop=0.0,
                module="sizing.score_tier_heatcap",
                risk_dollars=target_value,
            ))

        ctx.bar_state.sized_orders = filled
        return PhaseResult(
            decision=filled,
            blocked=False,
            reason=(
                f"{len(filled)} entries sized by X/4 tier, {skipped_cash} cash-exhausted, "
                f"{declined_score} below-min-score, {declined_missing} missing-score-declined"
            ),
            facts={
                "filled": len(filled),
                "committed_cash": committed_cash,
                "skipped_cash": skipped_cash,
                "declined_score": declined_score,
                "declined_missing": declined_missing,
            },
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "score_tier_heatcap_v1"
