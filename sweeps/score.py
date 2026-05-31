"""ADR-0001 D5 scoring (#214 component 5) — overfitting defense, baked in.

Implements the four D5 overfitting defenses as a composite score the leaderboard ranks on.
Citing ADR-0001 §D5 (docs/ARCHITECTURE.md):

  D5.2  Rank by STABILITY, not peak.   stability = mean(Sharpe) / std(Sharpe) across the 6
        windows (robust alpha), NOT best-window Sharpe. A high-peak / high-variance config
        scores BELOW a steady one — the central anti-curve-fit lever.
  D5.3  Complexity penalty (Occam).    a per-strategy deflation proportional to total swept
        free params (DoF). At equal raw stability the simpler config wins. Penalty is
        SUBTRACTED from stability, so it cannot be gamed by a config that buys a marginal
        stability gain with many extra knobs.
  D5.4  Robustness surface.            for a config we already have its window distribution;
        the robustness term rewards FLAT, penalises KNIFE-EDGE. Operationalised as the
        Sharpe dispersion (std) of the config — a config whose windows agree (low std) is
        flat; one that swings (high std) is a knife-edge. (A literal local-grid re-run around
        the optimum is the integration-flagged real-backtest step; the UNIT-testable surrogate
        here is the cross-window dispersion, which is computed with ZERO extra backtests.)
  D5.5  DoF budget per strategy.       a soft cap on total swept params; over-budget configs
        are flagged loudly. Enforced at enumeration (enumerate.apply_dof_budget); re-checked
        here so a scored row carries its budget verdict.

The composite (the leaderboard primary key):

    stability        = mean(Sharpe) / std(Sharpe)              [D5.2; std floored to avoid /0]
    complexity_pen   = COMPLEXITY_WEIGHT * total_free_params    [D5.3]
    robustness_pen   = ROBUSTNESS_WEIGHT * sharpe_std           [D5.4; knife-edge penalty]
    composite        = stability - complexity_pen - robustness_pen

Higher composite = better. The formula is intentionally SUBTRACTIVE and transparent (no
opaque product / exponent): each defense is a visible deduction a reviewer can read off the
leaderboard. Weights are module constants, tunable per sweep, defaulted conservative.

Judgement calls (flagged for review):
  - std floor (STD_FLOOR): a zero-variance config would give infinite stability. We floor
    std at a small epsilon so a perfectly-flat-but-thin result is finite, not infinite. This
    means a genuinely steady config is rewarded but not unboundedly.
  - robustness surrogate: cross-window std (a measure we already have) stands in for a
    literal local-grid re-run in the UNIT layer (zero backtests). The real grid re-run is the
    integration adapter's job; the surrogate makes the knife-edge penalty unit-testable and
    keeps the build compute-free, as the #214 HQ constraint requires.
"""
from __future__ import annotations

from dataclasses import dataclass

from sweeps.aggregate import AggregateResult
from sweeps.enumerate import DEFAULT_DOF_BUDGET

# --- Tunable scoring weights (ADR D5). Conservative defaults; a sweep may override. --- #
COMPLEXITY_WEIGHT = 0.05
"""Per-free-param deflation (D5.3). 8 DoF -> 0.40 deducted from stability — enough to flip a
marginal complex winner under a simpler near-equal config, small enough not to dominate a
genuinely large stability edge."""

ROBUSTNESS_WEIGHT = 0.10
"""Knife-edge penalty per unit of cross-window Sharpe std (D5.4). A config swinging by 1.0
Sharpe across windows loses 0.10 — a flat config loses ~0."""

STD_FLOOR = 0.05
"""Floor on Sharpe std so a (near-)zero-variance config gives FINITE, not infinite,
stability. Judgement call — see module docstring."""


@dataclass(frozen=True, slots=True)
class ScoredConfig:
    """A config's full D5 scorecard — the leaderboard row payload.

    `stability` (D5.2), `complexity_penalty` (D5.3), `robustness_penalty` (D5.4), and the
    resulting `composite`. `over_dof_budget` (D5.5) flags a config exceeding the soft DoF
    cap. Carries the underlying AggregateResult so the leaderboard can emit the metrics trio.
    """

    aggregate: AggregateResult
    stability: float
    complexity_penalty: float
    robustness_penalty: float
    composite: float
    total_free_params: int
    over_dof_budget: bool

    @property
    def config_hash(self) -> str:
        return self.aggregate.config.config_hash


def stability(agg: AggregateResult) -> float:
    """D5.2 — mean(Sharpe)/std(Sharpe) across windows. Std floored at STD_FLOOR.

    This is the primary robust-alpha measure: it rewards a config whose edge PERSISTS across
    windows and punishes one that depends on a single lucky window. Rank-by-stability (not
    rank-by-peak) is the central D5 defense.
    """
    std = max(agg.sharpe.std, STD_FLOOR)
    return agg.sharpe.mean / std


def complexity_penalty(total_free_params: int) -> float:
    """D5.3 — Occam deflation proportional to swept DoF."""
    return COMPLEXITY_WEIGHT * total_free_params


def robustness_penalty(agg: AggregateResult) -> float:
    """D5.4 — knife-edge penalty: proportional to cross-window Sharpe dispersion.

    Flat (windows agree, low std) -> ~0 penalty. Knife-edge (windows swing, high std) ->
    large penalty. The unit-testable surrogate for a local-grid re-run (see module docstring).
    """
    return ROBUSTNESS_WEIGHT * agg.sharpe.std


def score(
    agg: AggregateResult,
    *,
    dof_budget: int = DEFAULT_DOF_BUDGET,
) -> ScoredConfig:
    """Compute the full D5 composite scorecard for one aggregated config.

    composite = stability - complexity_penalty - robustness_penalty. Higher is better. The
    DoF-budget verdict (D5.5) is attached but does NOT alter the composite here — over-budget
    configs are normally already dropped at enumeration; if one is scored anyway, the flag
    surfaces it on the leaderboard.
    """
    dof = agg.config.total_free_params
    stab = stability(agg)
    comp_pen = complexity_penalty(dof)
    robust_pen = robustness_penalty(agg)
    composite = stab - comp_pen - robust_pen
    return ScoredConfig(
        aggregate=agg,
        stability=stab,
        complexity_penalty=comp_pen,
        robustness_penalty=robust_pen,
        composite=composite,
        total_free_params=dof,
        over_dof_budget=dof > dof_budget,
    )
