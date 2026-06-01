"""CPCV tests (#323 B.3) — split count, embargo length, purge overlap.

Index-level fixtures only — ZERO backtest.
"""
from __future__ import annotations

import math

import pytest

from sweeps.objective.cpcv import cpcv_splits, n_cpcv_paths


def test_split_count_is_C_groups_test() -> None:
    splits = cpcv_splits(120, n_groups=6, n_test_groups=2, embargo_frac=0.0)
    assert len(splits) == math.comb(6, 2) == n_cpcv_paths(6, 2) == 15


def test_test_and_train_are_disjoint() -> None:
    for s in cpcv_splits(120, n_groups=6, n_test_groups=2, embargo_frac=0.0):
        assert set(s.test_idx).isdisjoint(s.train_idx)


def test_no_embargo_no_purge_train_is_exact_complement() -> None:
    for s in cpcv_splits(120, n_groups=6, n_test_groups=2, embargo_frac=0.0):
        assert len(s.train_idx) + len(s.test_idx) == 120


def test_embargo_removes_ceil_frac_obs_after_each_test_block() -> None:
    # 100 obs, 5 groups (20 each), 1 test group, embargo 0.05 -> ceil(5)=5 obs trimmed after
    # the test block (except when the test block is the LAST group -> nothing after it).
    splits = cpcv_splits(100, n_groups=5, n_test_groups=1, embargo_frac=0.05)
    # split 0 tests group 0 (idx 0..19); embargo trims idx 20..24 from train.
    s0 = splits[0]
    assert set(range(20, 25)).isdisjoint(s0.train_idx)
    assert len(s0.train_idx) == 100 - 20 - 5
    # last split tests the final group -> no post-block obs to embargo.
    s_last = splits[-1]
    assert len(s_last.train_idx) == 100 - 20


def test_purge_removes_train_obs_inside_a_test_touching_trade_span() -> None:
    # A trade spanning [18, 35] touches test group 0 (0..19) -> its whole span is purged from
    # train, including the train-side tail (20..35).
    spans = [(18, 35)]
    splits = cpcv_splits(
        100, n_groups=5, n_test_groups=1, embargo_frac=0.0, trade_spans=spans
    )
    s0 = splits[0]  # test = 0..19
    assert set(range(18, 36)).isdisjoint(s0.train_idx)


def test_purge_leaves_non_overlapping_trades_alone() -> None:
    # A trade entirely in train (60..70), no test overlap -> not purged.
    spans = [(60, 70)]
    splits = cpcv_splits(
        100, n_groups=5, n_test_groups=1, embargo_frac=0.0, trade_spans=spans
    )
    s0 = splits[0]  # test = 0..19 ; 60..70 is well clear
    assert set(range(60, 71)).issubset(set(s0.train_idx))


def test_rejects_bad_group_params() -> None:
    with pytest.raises(ValueError):
        cpcv_splits(100, n_groups=1, n_test_groups=1)
    with pytest.raises(ValueError):
        cpcv_splits(100, n_groups=5, n_test_groups=5)  # test must be < groups
    with pytest.raises(ValueError):
        cpcv_splits(3, n_groups=5, n_test_groups=1)  # n_obs < n_groups
