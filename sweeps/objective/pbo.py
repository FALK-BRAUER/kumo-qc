"""Probability of Backtest Overfitting via CSCV (#323 B.2) — Bailey et al. (2017).

PBO is a GLOBAL overfitting measure of the WHOLE sweep, not a per-config one: the probability
that the config which looked best IN-SAMPLE is BELOW-MEDIAN OUT-OF-SAMPLE. A high PBO means
the search is fitting noise — the in-sample winner has no out-of-sample edge.

Combinatorially-Symmetric Cross-Validation:
  1. Build a matrix M [T_observations × N_configs] of per-period performance (here: per-period
     returns; the IS/OS metric is the per-slice Sharpe).
  2. Partition the T rows into `n_splits` disjoint, CONTIGUOUS sub-matrices (n_splits even).
  3. For each of the C(n_splits, n_splits/2) ways to pick half the sub-matrices as IN-SAMPLE
     (the rest are OUT-OF-SAMPLE):
       - n*  = argmax_c Sharpe_IS(c)          (best config in-sample)
       - r   = OS rank of n* among all configs (1 = worst .. N = best, OS Sharpe)
       - ω   = r / (N + 1)                     (relative OS rank in (0,1))
       - λ   = logit(ω) = ln(ω / (1 - ω))      (>0 ⇒ above OS median, <0 ⇒ below)
  4. PBO = P(λ ≤ 0) = fraction of combinations where the IS-best is at-or-below the OS median.

`PBO < 0.2` is the #323 filter threshold. The full λ distribution + the IS-vs-OS Sharpe pairs
are retained as a loop-forensics artifact (the IS→OS degradation scatter).

Computed on the EXISTING return matrix — ZERO extra backtests (the compute-free boundary).
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PBOResult:
    """The CSCV outcome: the scalar PBO + the full λ distribution + IS/OS pairs (forensics)."""

    pbo: float
    logit_lambdas: tuple[float, ...]
    is_os_pairs: tuple[tuple[float, float], ...]  # (IS Sharpe of best, OS Sharpe of best)

    @property
    def n_combinations(self) -> int:
        return len(self.logit_lambdas)


def _slice_sharpe(values: Sequence[float]) -> float:
    """Per-slice Sharpe = mean/std (population). 0.0 if no dispersion (a flat slice)."""
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    if n < 2:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(var)
    return 0.0 if std == 0.0 else mean / std


def _contiguous_blocks(n_obs: int, n_splits: int) -> list[tuple[int, ...]]:
    """Partition range(n_obs) into n_splits contiguous index blocks (front-loaded remainder)."""
    base = n_obs // n_splits
    rem = n_obs % n_splits
    blocks: list[tuple[int, ...]] = []
    start = 0
    for s in range(n_splits):
        size = base + (1 if s < rem else 0)
        blocks.append(tuple(range(start, start + size)))
        start += size
    return blocks


def cscv_pbo(
    return_matrix: Mapping[str, Sequence[float]], *, n_splits: int = 16
) -> PBOResult:
    """PBO over the [T × N] return matrix (config_hash -> per-period returns, equal length).

    Requires n_splits even (symmetric IS/OS halves) and at least 2 configs (PBO is undefined
    for a single config — there is no "median to fall below"). Every config's series must be
    the same length T (they are the SAME time axis). Returns the PBO + the λ distribution.
    """
    if n_splits % 2 != 0:
        raise ValueError("n_splits must be even (CSCV draws symmetric IS/OS halves)")
    configs = list(return_matrix.keys())
    n_configs = len(configs)
    if n_configs < 2:
        raise ValueError("PBO needs >= 2 configs (no median to rank against otherwise)")
    lengths = {len(return_matrix[c]) for c in configs}
    if len(lengths) != 1:
        raise ValueError(f"all configs must share one time axis; got lengths {lengths}")
    n_obs = lengths.pop()
    if n_obs < n_splits:
        raise ValueError(f"n_obs={n_obs} < n_splits={n_splits}")

    blocks = _contiguous_blocks(n_obs, n_splits)
    half = n_splits // 2

    lambdas: list[float] = []
    pairs: list[tuple[float, float]] = []
    for is_blocks in itertools.combinations(range(n_splits), half):
        is_set = set(is_blocks)
        is_idx: list[int] = []
        os_idx: list[int] = []
        for bi, block in enumerate(blocks):
            (is_idx if bi in is_set else os_idx).extend(block)

        # IS Sharpe per config → pick the in-sample best.
        is_sharpes = {c: _slice_sharpe([return_matrix[c][i] for i in is_idx]) for c in configs}
        best = max(configs, key=lambda c: is_sharpes[c])

        # OS Sharpe per config → relative OS rank of the IS-best.
        os_sharpes = {c: _slice_sharpe([return_matrix[c][i] for i in os_idx]) for c in configs}
        # rank: 1 = worst .. N = best (ties broken by config hash for determinism).
        ordered = sorted(configs, key=lambda c: (os_sharpes[c], c))
        rank = ordered.index(best) + 1  # 1-based
        omega = rank / (n_configs + 1)
        omega = min(max(omega, 1e-9), 1.0 - 1e-9)  # keep logit finite at the extremes
        lam = math.log(omega / (1.0 - omega))
        lambdas.append(lam)
        pairs.append((is_sharpes[best], os_sharpes[best]))

    pbo = sum(1 for lam in lambdas if lam <= 0.0) / len(lambdas)
    return PBOResult(
        pbo=pbo,
        logit_lambdas=tuple(lambdas),
        is_os_pairs=tuple(pairs),
    )
