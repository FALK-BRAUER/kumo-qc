"""Signal phase: OracleSignal — the #322 PROD-PHASE BRIDGE for the kumo-lab #303 mine.

Kind: signal
Marker: oracle_signal_v1
Resolution: daily (the decision clock — same as BctScoreFull; the qualify lane only).

WHAT THIS IS
------------
OracleSignal is a DROP-IN signal phase that parallels (and can replace) BctScoreFull. It runs
the EXACT same phase contract — `Params`, `evaluate(ctx) -> PhaseResult`, reads
`ctx.bar_state.ranked_candidates` + `qc._indicators`, emits the surviving candidates to
`ctx.bar_state.sized_orders` as `qty=0` OrderIntent stubs (the sizing phase sets qty), never
blocks — so it is a no-touch Slot swap in any strategy config that currently wires BctScoreFull.

The difference is WHERE the per-candidate decision comes from. BctScoreFull hard-codes the
8-condition BCT sum + a `score >= min_score` gate. OracleSignal delegates the decision to an
INJECTED PREDICTOR (`Params.predictor`) — the LEARNED model the kumo-lab #303 mine produces
over the per-candidate feature vector (the 8 BCT conditions + gap / vol / regime / rank, mapped
to the realized R-outcome). The seam is the whole point: the strategy keeps the same phase
stack, and the lab swaps the hand-coded score for a learned predictor by handing us a
`Predictor` that satisfies the interface below.

THE SEAM (#322)
---------------
- The DEFAULT predictor is `BctPassthroughPredictor` — a stub that REPRODUCES BctScoreFull:
  score = the 8-condition sum (via `score_from_daily_frame`-equivalent maintained-indicator
  scorer `score_symbol_native`), fire iff `score >= min_score`. With the stub,
  `OracleSignal == BctScoreFull` on the same fixture (the no-op-swap parity baseline — proves
  the seam is wired correctly and is behaviour-neutral until a real predictor lands).
- The lab fills in a real `Predictor` LATER (Falk's call to wire it into a champion). This file
  ships the INTERFACE + the stub NOW; it is NOT wired into any champion config.

FAIL-LOUD (charter)
-------------------
A predictor that returns a non-finite (NaN/inf) or otherwise invalid score RAISES
`PredictorError` — the engine must NEVER fire a trade on a garbage score (the anti-mirage
mandate: an outage/degraded model crashes loudly, never silently passes a wrong decision).

Changelog:
  v1  #322 prod-phase bridge: Predictor interface + CandidateFeatures contract + BctPassthrough
      stub (== BctScoreFull parity) + fail-loud on non-finite score.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from engine.base import BasePhase, PhaseResult
from engine.symbol_key import canonical_symbol_key
from engine.context import OrderIntent, PhaseContext
from phases.shared.oracle_helpers import score_symbol_native
from phases.shared.param_space import ComplexityDecl, ParamSpace


# ---------------------------------------------------------------------------
# Engine exception (fail-loud seam). Local to the phase so the greenfield scope
# does NOT touch engine/base.py; the engine catches Exception at the phase boundary
# and a PredictorError is a hard, diagnosable crash carrying the offending ticker.
# ---------------------------------------------------------------------------
class PredictorError(Exception):
    """Raised when an injected predictor returns an invalid (non-finite / out-of-contract)
    output. The anti-mirage contract on the LEARNED model: a garbage score must CRASH with
    the offending ticker, NEVER fire a trade. Carries the ticker + the bad value in its
    message — not a bare assert."""


# ---------------------------------------------------------------------------
# THE FEATURE CONTRACT — what the lab's #322 predictor consumes.
#
# This is the per-candidate feature VECTOR available at the daily decision (after close T,
# for T+1). It is the input the #303 mine learns over, and the input every Predictor.predict()
# receives. Aligned to (a) the 8 BCT conditions (score_symbol_native / score_from_daily_frame)
# and (b) the daily features the (B) generator emits at decision time. Every field is computed
# WITHOUT look-ahead — values are as-of the decision close.
#
# The lab's model MUST be a function of (a subset of) these fields. If the lab needs a feature
# not present here, ADD IT to this dataclass (and to `_build_features` below) — do NOT smuggle
# a feature in via the qc handle, so the contract stays the single source of truth.
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class CandidateFeatures:
    """The per-candidate feature vector at the daily decision (no look-ahead).

    FEATURE CONTRACT (#322) — the lab's predictor is a function of these fields:

    Identity / bookkeeping (not learned over directly, carried for the predictor's context):
      ticker     : the canonical (upper) symbol value.
      price      : the live decision-close price (> 0; the security price at decision).

    The 8 BCT conditions (the Blue Flag checklist, in canonical order; True == condition met):
      conditions : tuple[bool, ...] of length 8 —
        [0] weekly price above cloud        [4] daily price above cloud
        [1] weekly tenkan > kijun           [5] daily price above tenkan
        [2] weekly chikou > price 26-ago    [6] ADX rising + +DI>-DI + ADX>=20
        [3] weekly cloud green              [7] price above 200MA
      bct_score  : sum(conditions) in 0..8 (the hand-coded BCT score; the stub fires on this).

    The daily decision features (gap / vol / regime / rank — the #303 mine's extra signal):
      roc13      : maintained 13-day rate-of-change (the parabolic/momentum feature). None if
                   the maintained indicator is not ready.
      dollar_vol : trailing-mean dollar volume (the liquidity / ranking feature). 0.0 if absent.
      rank       : 0-based position of this candidate in the universe's ranked_candidates list
                   (the universe phase's liquidity/price rank at the selection gate).
      regime_ok  : whether the daily regime gate is permissive for this bar (True == risk-on).
                   None when no regime signal is available to the phase.

    Notes for the lab:
      - This is intentionally a SUPERSET of what BctScoreFull uses (which is only `bct_score`
        + the pre-filter conditions). The passthrough stub ignores everything but `bct_score`.
      - gap is represented by `roc13` here (the maintained momentum proxy the engine carries);
        an explicit overnight-gap feature can be added when the lab needs it.
      - `regime_ok` is surfaced for completeness; the signal/qualify lane does not itself gate on
        regime (the regime phase does, downstream) — the predictor MAY still use it as a feature.
    """

    ticker: str
    price: float
    conditions: tuple[bool, ...]
    bct_score: int
    roc13: float | None = None
    dollar_vol: float = 0.0
    rank: int = 0
    regime_ok: bool | None = None


# ---------------------------------------------------------------------------
# THE PREDICTOR INTERFACE — what the lab's #322 model must satisfy.
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class PredictorOutput:
    """The output of `Predictor.predict()` for one candidate.

    score : a finite float — the predictor's quality estimate (a BCT-style 0..8 score, a
            calibrated probability, or any monotone quality ranking; HIGHER == better). MUST be
            finite (a NaN/inf raises PredictorError at the phase boundary). Used for ranking
            survivors (score DESC, dollar_vol DESC) — same ordering contract as BctScoreFull.
    fire  : the fire / no-fire decision for THIS candidate. The phase emits the candidate iff
            `fire` is True. The predictor owns the threshold logic (the stub fires at
            `score >= min_score`; a learned model may fire on a probability cut, a calibrated
            threshold, etc.). The phase does NOT re-threshold — it trusts `fire`.
    """

    score: float
    fire: bool


@runtime_checkable
class Predictor(Protocol):
    """Structural contract for an OracleSignal predictor (the #322 learned-model seam).

    A predictor is any object (or callable wrapper) exposing:

        def predict(self, features: CandidateFeatures) -> PredictorOutput: ...

    INPUT  : a fully-populated `CandidateFeatures` (the feature contract above) for ONE candidate
             at the daily decision.
    OUTPUT : a `PredictorOutput` (finite `score` + `fire` decision).

    The lab's #303 model satisfies this by wrapping its trained estimator so `predict` maps the
    feature vector to (score, fire-at-threshold). The phase calls `predict` once per surviving
    pre-filtered candidate; a non-finite score raises (fail-loud)."""

    def predict(self, features: CandidateFeatures) -> PredictorOutput: ...


@dataclass(slots=True, frozen=True)
class BctPassthroughPredictor:
    """The DEFAULT stub predictor — REPRODUCES BctScoreFull exactly (the no-op-swap baseline).

    score = the 8-condition BCT sum (features.bct_score); fire iff score >= min_score. With this
    predictor, OracleSignal's surviving set + ranking == BctScoreFull's on the same inputs (the
    seam is behaviour-neutral until the lab ships a learned predictor). Stateless + frozen — safe
    to share across the sweep grid."""

    min_score: int = 7

    def predict(self, features: CandidateFeatures) -> PredictorOutput:
        score = float(features.bct_score)
        return PredictorOutput(score=score, fire=features.bct_score >= self.min_score)


@dataclass(slots=True, frozen=True)
class DvRankPredictor:
    """#322 LEARNED SIGNAL v1 — BCT pool + DV-rank edge (the phase-1 mine finding, PHASE1_FINDINGS.md).

    The mine's durable result: among score≥7 names, the 8 BCT conditions do NOT further-separate
    winners from losers, but DV/liquidity RANK does — high-DV-rank names ride to winners, low-DV
    names stop out, robust across 4/4 testable regimes (FY2021 +33pp ... FY2023-bear +6pp). So the
    learned signal keeps the BCT screen as the POOL (score≥min_score, table-stakes) and adds the
    DV-rank EDGE: fire only the top-liquidity slice (rank ≤ rank_cap; rank is 0-based DV-desc, so a
    LOWER rank = HIGHER dollar-volume). `score` blends the pool strength with a bounded DV bonus so
    survivors ORDER by (BCT score, then liquidity) — the bonus is a tie-break in [0,1), it never
    lifts a sub-pool (score<min_score) name into firing.

    rank_cap is the learned edge knob — the DV-liquidity ceiling. A first-cut hypothesis-grade
    value; the rigorous mine (Falk-gated counterfactual) calibrates it. Stateless + frozen."""

    min_score: int = 7
    rank_cap: int = 300

    def predict(self, features: CandidateFeatures) -> PredictorOutput:
        in_pool = features.bct_score >= self.min_score
        in_edge = features.rank <= self.rank_cap
        # dv_bonus is STRICTLY in [0, 1) — the (rank_cap + 1) denominator keeps even rank-0 (top DV)
        # below 1.0, so the bonus is a pure within-tier tie-break: a score-7 name can never tie or
        # outrank a score-8 name (the BCT pool tier always dominates the liquidity bonus).
        dv_bonus = max(0.0, (self.rank_cap - features.rank) / (self.rank_cap + 1))
        return PredictorOutput(score=float(features.bct_score) + dv_bonus, fire=in_pool and in_edge)


class OracleSignal(BasePhase):
    PHASE_KIND = "signal"
    PHASE_RESOLUTION = "daily"  # decision clock — qualify lane only (same as BctScoreFull)
    REQUIRES_UPSTREAM = ["universe"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    # ADR D5 overfitting-defense. The HAND-CODED knobs the phase exposes to a sweep are
    # min_score + parabolic_threshold (the pre-filter / parabolic block it shares with
    # BctScoreFull). The predictor itself is an INJECTED object, NOT a swept scalar axis — its
    # internal hyperparameters are the lab's complexity to declare, not this phase's. So this
    # phase declares the same 2 free params as BctScoreFull.
    COMPLEXITY = ComplexityDecl(
        free_params=2,
        note="min_score (passthrough fire threshold + pre-filter) + parabolic_threshold "
        "(overextension block). The injected predictor's own params are the lab's to declare.",
    )

    @dataclass(slots=True)
    class Params:
        # The injected/pluggable predictor (the #322 seam). Defaults to the passthrough stub
        # that reproduces BctScoreFull. The lab swaps a learned Predictor here.
        predictor: Predictor = field(default_factory=BctPassthroughPredictor)
        # min_score: the pre-filter ceiling (a name below 200MA or below cloud cannot reach this)
        # AND the stub's fire threshold. A learned predictor owns its own threshold (via `fire`),
        # but min_score still drives the cheap pre-filter that keeps scoring cost down.
        min_score: int = 7
        parabolic_threshold: float = 0.25
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axes (mirrors BctScoreFull). The predictor is NOT a swept axis here —
            it is an injected object; its hyperparameters are the lab's to sweep upstream."""
            return ParamSpace(
                axes={
                    "min_score": (6, 7, 8),
                    "parabolic_threshold": (0.20, 0.25, 0.30, 0.35),
                }
            )

    def __init__(self, params: "OracleSignal.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def _build_features(
        self,
        ticker: str,
        price: float,
        score_result: dict[str, Any],
        roc13_val: float | None,
        dollar_vol: float,
        rank: int,
        regime_ok: bool | None,
    ) -> CandidateFeatures:
        """Assemble the per-candidate feature vector (the FEATURE CONTRACT) from the maintained
        scorer result + the engine's daily features. The single place features are built — keeps
        the contract honest (no feature reaches the predictor except through here)."""
        conditions = tuple(bool(c) for c in score_result.get("conditions", ()))
        return CandidateFeatures(
            ticker=ticker,
            price=price,
            conditions=conditions,
            bct_score=int(score_result["score"]),
            roc13=roc13_val,
            dollar_vol=dollar_vol,
            rank=rank,
            regime_ok=regime_ok,
        )

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        min_score = self.p.min_score
        parabolic_threshold = self.p.parabolic_threshold
        predictor = self.p.predictor

        candidates_raw = ctx.bar_state.ranked_candidates  # list of str symbol values
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}  # #276b-1 FIX3
        trailing_dv = getattr(qc, "_trailing_dv", {})
        # Regime feature (optional): None if the engine has not stamped one for this bar.
        regime_ok = getattr(qc, "_regime_ok", None)

        candidates: list[tuple[Any, float, float]] = []  # (symbol, predictor_score, dollar_vol)
        blocked_log: list[str] = []
        fired_no_count = 0  # candidates the predictor scored but declined to fire

        for rank, ticker in enumerate(candidates_raw):
            symbol = active_by_key.get(canonical_symbol_key(ticker))
            if symbol is None:
                continue
            if qc.portfolio[symbol].invested:
                continue
            if qc.transactions.get_open_orders(symbol):
                continue

            ind = getattr(qc, "_indicators", {}).get(symbol)
            if ind is None:
                continue

            # PRE-FILTER (identical to BctScoreFull): skip names that cannot reach min_score.
            # This is a CHEAP structural gate that bounds scoring cost; it does NOT pre-judge the
            # predictor's decision (a name that passes the pre-filter still goes through predict).
            sma200_ind = ind.get("sma200")
            d_ichi_ind = ind.get("d_ichi")
            if sma200_ind and sma200_ind.is_ready and d_ichi_ind and d_ichi_ind.is_ready:
                price = float(qc.securities[symbol].price)
                if price <= 0:
                    continue
                if price < sma200_ind.current.value:
                    continue  # condition 8 fails → max score 6 → skip
                cloud_top = max(d_ichi_ind.senkou_a.current.value, d_ichi_ind.senkou_b.current.value)
                if price < cloud_top:
                    continue  # condition 5 fails → max score 6 → skip

            # Score the 8 BCT conditions (the feature core). None == warmup/NaN → skip.
            score_result = score_symbol_native(qc, symbol, ind)
            if score_result is None:
                continue

            # Parabolic entry block (identical to BctScoreFull): skip over-extended names.
            roc13 = ind.get("roc13")
            roc13_val: float | None = None
            if roc13 is not None and roc13.is_ready:
                roc13_val = float(roc13.current.value)
                if roc13_val > parabolic_threshold:
                    blocked_log.append(ticker)
                    continue

            dollar_vol = float(trailing_dv.get(ticker.lower(), 0.0))
            price = float(qc.securities[symbol].price)

            # THE SEAM: build the feature vector and ask the predictor.
            features = self._build_features(
                ticker=ticker,
                price=price,
                score_result=score_result,
                roc13_val=roc13_val,
                dollar_vol=dollar_vol,
                rank=rank,
                regime_ok=regime_ok,
            )
            output = predictor.predict(features)

            # FAIL-LOUD: a non-finite / non-numeric score is a degraded model — crash, never fire.
            score = output.score
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(float(score)):
                raise PredictorError(
                    f"predictor returned a non-finite score for {ticker!r}: {score!r} "
                    f"(type {type(score).__name__}). A degraded model must crash, never fire."
                )

            if not output.fire:
                fired_no_count += 1
                continue

            candidates.append((symbol, float(score), dollar_vol))

        # Rank survivors: score DESC, dollar_vol DESC — same ordering contract as BctScoreFull.
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

        ctx.bar_state.sized_orders = [
            OrderIntent(
                ticker=sym.value,
                qty=0,
                price=float(qc.securities[sym].price),
                stop=0.0,
                module="signal.oracle_signal",
                risk_dollars=0.0,
            )
            for sym, _score, _dv in candidates
        ]

        return PhaseResult(
            decision=candidates,
            blocked=False,
            reason=(
                f"{len(candidates)} candidates fired by predictor, "
                f"{fired_no_count} declined, {len(blocked_log)} parabolic blocks"
            ),
            facts={
                "candidate_count": len(candidates),
                "parabolic_blocked": len(blocked_log),
                "predictor_declined": fired_no_count,
                "predictor": type(predictor).__name__,
            },
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "oracle_signal_v1"
