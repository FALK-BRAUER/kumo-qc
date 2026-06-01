"""The #323 selector (B.5) — lexicographic FILTER then weighted SCORE then champion-beat.

This is the new TOP-LEVEL decision rule, replacing sweeps/score.py's D5 composite AS THE
SELECTOR (the composite stays a diagnostic column elsewhere). Order:

  1. FILTER (lexicographic, HARD) — any miss → REJECT-<gate>, excluded from scoring but kept
     on the leaderboard with its reason (transparency):
        PBO < 0.2  AND  DSR > 0.8  AND  trade-count gate  AND  concentration guard.
     (Filters operate at the SWEEP level for PBO, per-config for the rest.)
  2. SCORE (survivors only, weighted, λ1 > λ2 > λ3 > λ4):
        score = λ1·DSR + λ2·(1 − PBO) + λ3·Calmar_norm + λ4·(−trade_penalty)
     Calmar = annualised_return / max_drawdown (the trio's DD% leg, DD-aware).
     trade_penalty = soft deflation as trade-count approaches the floor (discourages a
     thin-edge config that just cleared the gate).
  3. MUST BEAT the COST-AWARE champion_intraday baseline (#321) on the trio. A config that
     scores well but doesn't beat the cost-aware champion is NOT a positive outcome.

THE #321 COST-BASELINE CONTRACT (coordination hook): the selector takes `champion_score` — a
single float that is the cost-aware champion_intraday's score UNDER THIS SAME objective. When
#321's re-baselined champion metric is available, the driver computes the champion's
ObjectiveScore the SAME way (same DSR/PBO/Calmar pipeline) and passes its `.score` here. Until
then, pass `champion_score=None` → `must_beat_champion` is left UNKNOWN (None) and surfaced as
a clearly-marked hook rather than silently asserting a beat. See `cost_baseline_hook` below.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sweeps.objective.gates import (
    MIN_TOTAL_TRADES,
    GateVerdict,
    WindowReturns,
    concentration_guard,
    trade_count_gate,
)

OBJECTIVE_VERSION = "323.v1"
"""Pins WHICH objective produced a score (B.5/A.7 / OQ-7). Re-tuning λ/thresholds → bump this;
rows from different objective versions are NOT comparable."""

FILTER = {
    "pbo_max": 0.2,
    "dsr_min": 0.8,
    "min_total_trades": MIN_TOTAL_TRADES,
}
"""The lexicographic FILTER thresholds (#323 B.5). A miss on any → REJECT."""

WEIGHTS = {
    "l1_dsr": 0.50,
    "l2_one_minus_pbo": 0.25,
    "l3_calmar": 0.15,
    "l4_trade_penalty": 0.10,
}
"""λ1 > λ2 > λ3 > λ4 — DSR dominates, then PBO, then Calmar, then the trade penalty."""

CALMAR_NORM = 3.0
"""Calmar is normalised by this (a Calmar of 3 ⇒ full λ3 credit) so the four terms are
roughly commensurate before weighting. A judgement constant — pinned by OBJECTIVE_VERSION."""


@dataclass(frozen=True, slots=True)
class ConfigEvidence:
    """Everything the selector needs for ONE config — the per-config objective inputs.

    `dsr`/`pbo` come from the objective layer (PBO is a sweep-global number broadcast to each
    config; DSR is per-config). `ann_return`/`max_dd` give Calmar. `n_trades` drives the trade
    penalty. `windows` feed the trade-count + concentration gates.
    """

    config_hash: str
    dsr: float
    pbo: float
    ann_return: float
    max_dd: float
    n_trades: int
    windows: tuple[WindowReturns, ...]


@dataclass(frozen=True, slots=True)
class ObjectiveScore:
    """One config's full #323 scorecard — the leaderboard row payload for the new selector."""

    config_hash: str
    dsr: float
    pbo: float
    calmar: float
    trade_penalty: float
    score: float
    filter_verdict: GateVerdict
    must_beat_champion: bool | None  # None == champion baseline not yet wired (#321 hook)
    objective_version: str = OBJECTIVE_VERSION


def calmar(ann_return: float, max_dd: float) -> float:
    """Calmar = annualised return / max drawdown magnitude. 0.0 if no drawdown is recorded.

    `max_dd` is a magnitude (>= 0). A config with positive return and a tiny DD has a large
    Calmar; one that bleeds has a small/negative one. Guards a zero/again-zero DD (no curve).
    """
    dd = abs(max_dd)
    if dd == 0.0:
        return 0.0
    return ann_return / dd


def trade_penalty(n_trades: int, floor: int = MIN_TOTAL_TRADES) -> float:
    """Soft deflation as trade-count approaches the floor → 0 well above it, → 1 AT the floor.

    penalty = max(0, (floor_buffer - (n - floor)) / floor_buffer) clamped to [0,1], where
    floor_buffer = floor (so a config with 2× the floor of trades has ~zero penalty, one
    exactly at the floor has the full penalty). Discourages thin-edge configs that just
    cleared the hard gate.
    """
    if n_trades <= floor:
        return 1.0
    buffer = floor
    excess = n_trades - floor
    return max(0.0, min(1.0, (buffer - excess) / buffer))


def _filter_verdict(ev: ConfigEvidence, *, pbo: float) -> GateVerdict:
    """Apply the lexicographic FILTER. First failing gate wins the reject reason."""
    tc = trade_count_gate(ev.windows)
    if not tc.passed:
        return tc
    cg = concentration_guard(ev.windows)
    if not cg.passed:
        return cg
    if pbo >= FILTER["pbo_max"]:
        return GateVerdict(False, f"REJECT-pbo: {pbo:.3f}>={FILTER['pbo_max']}")
    if ev.dsr <= FILTER["dsr_min"]:
        return GateVerdict(False, f"REJECT-dsr: {ev.dsr:.3f}<={FILTER['dsr_min']}")
    return GateVerdict(True)


def cost_baseline_hook(champion_metric: object | None) -> float | None:
    """#321 coordination hook — resolve the cost-aware champion_intraday score.

    CONTRACT: when #321's re-baselined champion_intraday metric is available, the driver
    computes its ObjectiveScore through THIS SAME pipeline and passes the resulting `.score`
    as a float here. Until then this returns None — a CLEARLY-MARKED absence, never a
    fabricated baseline. `must_beat_champion` is then None (unknown), surfaced on the
    leaderboard rather than silently asserting a beat.
    """
    if champion_metric is None:
        return None
    if isinstance(champion_metric, (int, float)):
        return float(champion_metric)
    raise TypeError(
        "champion baseline must be a numeric objective score (the cost-aware "
        f"champion_intraday's ObjectiveScore.score), got {type(champion_metric).__name__}. "
        "See the #321 cost-baseline contract in selector.cost_baseline_hook."
    )


def score_config(ev: ConfigEvidence, *, pbo: float, champion_score: float | None) -> ObjectiveScore:
    """Score ONE config: filter, then (if passing) the weighted score + champion-beat check.

    A REJECTED config gets `score=0.0` and `must_beat_champion=None` but is RETAINED (the
    caller keeps it on the leaderboard with its reject reason — transparency).
    """
    verdict = _filter_verdict(ev, pbo=pbo)
    cal = calmar(ev.ann_return, ev.max_dd)
    tp = trade_penalty(ev.n_trades)
    if not verdict.passed:
        return ObjectiveScore(
            config_hash=ev.config_hash,
            dsr=ev.dsr,
            pbo=pbo,
            calmar=cal,
            trade_penalty=tp,
            score=0.0,
            filter_verdict=verdict,
            must_beat_champion=None,
        )
    score = (
        WEIGHTS["l1_dsr"] * ev.dsr
        + WEIGHTS["l2_one_minus_pbo"] * (1.0 - pbo)
        + WEIGHTS["l3_calmar"] * (cal / CALMAR_NORM)
        + WEIGHTS["l4_trade_penalty"] * (-tp)
    )
    beats: bool | None
    beats = None if champion_score is None else (score > champion_score)
    return ObjectiveScore(
        config_hash=ev.config_hash,
        dsr=ev.dsr,
        pbo=pbo,
        calmar=cal,
        trade_penalty=tp,
        score=score,
        filter_verdict=verdict,
        must_beat_champion=beats,
    )


def select(
    evidence: Sequence[ConfigEvidence],
    *,
    pbo: float,
    champion_score: float | None = None,
) -> list[ObjectiveScore]:
    """Score + RANK every config. `pbo` is the sweep-global CSCV PBO (broadcast to each config).

    Returns ALL configs (survivors AND rejects, the rejects for transparency) sorted so
    PASSING configs come first, by descending score; rejects trail, ordered by config_hash for
    determinism. `champion_score` is the #321 cost-aware baseline (None → unknown, see hook).
    """
    scored = [
        score_config(ev, pbo=pbo, champion_score=champion_score) for ev in evidence
    ]

    def _key(s: ObjectiveScore) -> tuple[int, float, str]:
        # passing first (0), then by score DESC, then config_hash for total order.
        return (0 if s.filter_verdict.passed else 1, -s.score, s.config_hash)

    return sorted(scored, key=_key)
