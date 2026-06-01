"""Combinatorial purged cross-validation + embargo (#323 B.3) — the OOS path estimator.

CPCV (López de Prado, *Advances in Financial Machine Learning*, ch. 12) generalises
single-split / k-fold / walk-forward: with `n_groups` contiguous time groups, choose
`n_test_groups` as TEST, train on the rest, repeated over ALL C(n_groups, n_test_groups)
combinations → MANY backtest paths → a DISTRIBUTION of OOS performance rather than one number.
That distribution feeds DSR's cross-trial variance and the loop's fall-apart detection.

Two leakage controls:
  - PURGE: drop TRAIN observations whose label/holding window overlaps ANY test observation.
    A trade open across the train/test boundary leaks test info into training. We purge by
    the trade's [entry, exit] interval (use TradeRecord) — any train obs inside a test trade's
    holding span is removed.
  - EMBARGO: after each contiguous TEST block, drop a buffer of the immediately-following
    TRAIN observations (serial correlation makes the bars right after a test block contaminated
    even without an overlapping trade). Embargo length = ceil(embargo_frac · n_obs).

This module re-slices the EXISTING per-period return/trade series the sweep already produced —
it does NOT re-run LEAN (the compute-free objective boundary, mock-testable).
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CPCVSplit:
    """One CPCV path: the train/test observation indices after purge + embargo.

    `test_idx` is the union of the chosen test groups (contiguous blocks). `train_idx` is the
    complement MINUS purged (overlap) MINUS embargoed (post-block buffer) observations.
    """

    train_idx: tuple[int, ...]
    test_idx: tuple[int, ...]


def _contiguous_groups(n_obs: int, n_groups: int) -> list[tuple[int, ...]]:
    """Partition range(n_obs) into n_groups CONTIGUOUS blocks (time order preserved).

    The first (n_obs % n_groups) groups get one extra obs so every obs is assigned exactly
    once (no dropped tail). Contiguity matters: CPCV groups are time blocks, not random folds.
    """
    if n_groups < 2:
        raise ValueError("need >= 2 groups for cross-validation")
    if n_obs < n_groups:
        raise ValueError(f"n_obs={n_obs} < n_groups={n_groups} — cannot form contiguous groups")
    base = n_obs // n_groups
    rem = n_obs % n_groups
    groups: list[tuple[int, ...]] = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < rem else 0)
        groups.append(tuple(range(start, start + size)))
        start += size
    return groups


def cpcv_splits(
    n_obs: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo_frac: float = 0.01,
    trade_spans: Sequence[tuple[int, int]] | None = None,
) -> list[CPCVSplit]:
    """All C(n_groups, n_test_groups) CPCV paths over n_obs observations.

    `trade_spans` — optional [(entry_idx, exit_idx), ...] holding intervals (inclusive) used
    for PURGE: a train obs is purged if it falls inside the holding span of a trade that
    touches any test obs. `embargo_frac` sets the post-test-block buffer length.

    Returns one CPCVSplit per combination, in deterministic combination order.
    """
    if not (1 <= n_test_groups < n_groups):
        raise ValueError("require 1 <= n_test_groups < n_groups")
    if not (0.0 <= embargo_frac < 1.0):
        raise ValueError("embargo_frac must be in [0, 1)")
    groups = _contiguous_groups(n_obs, n_groups)
    embargo = math.ceil(embargo_frac * n_obs)

    splits: list[CPCVSplit] = []
    for combo in itertools.combinations(range(n_groups), n_test_groups):
        test_idx_set: set[int] = set()
        for gi in combo:
            test_idx_set.update(groups[gi])
        train_idx_set: set[int] = set(range(n_obs)) - test_idx_set

        # EMBARGO: drop the `embargo` train obs immediately AFTER each contiguous test block.
        if embargo > 0:
            for gi in combo:
                block = groups[gi]
                last = block[-1]
                for j in range(last + 1, min(last + 1 + embargo, n_obs)):
                    train_idx_set.discard(j)

        # PURGE: drop train obs inside the holding span of any trade touching a test obs.
        if trade_spans:
            for entry, exit_ in trade_spans:
                lo, hi = (entry, exit_) if entry <= exit_ else (exit_, entry)
                touches_test = any(lo <= t <= hi for t in test_idx_set)
                if touches_test:
                    for j in range(lo, hi + 1):
                        train_idx_set.discard(j)

        splits.append(
            CPCVSplit(
                train_idx=tuple(sorted(train_idx_set)),
                test_idx=tuple(sorted(test_idx_set)),
            )
        )
    return splits


def n_cpcv_paths(n_groups: int, n_test_groups: int) -> int:
    """C(n_groups, n_test_groups) — the number of CPCV paths (split count). For the cost log."""
    return math.comb(n_groups, n_test_groups)
