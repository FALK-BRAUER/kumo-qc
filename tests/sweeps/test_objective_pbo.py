"""PBO/CSCV tests (#323 B.2) — robust vs overfit vs adversarial synthetic sets.

Synthetic return matrices only — ZERO backtest.
"""
from __future__ import annotations

import math
import random

import pytest

from sweeps.objective.pbo import cscv_pbo


def test_combination_count_is_C_n_half() -> None:
    # n_splits=8 -> C(8,4)=70 IS/OS combinations.
    mat = {f"c{i}": [random.Random(i).gauss(0, 0.01) for _ in range(64)] for i in range(3)}
    r = cscv_pbo(mat, n_splits=8)
    assert r.n_combinations == math.comb(8, 4)
    assert len(r.logit_lambdas) == r.n_combinations
    assert len(r.is_os_pairs) == r.n_combinations


def test_pbo_robust_set_is_low() -> None:
    # One config dominates IS AND OS in every slice -> the IS-best is OS-best -> PBO ~ 0.
    rng = random.Random(11)
    T = 160
    good = [0.01 + rng.gauss(0, 0.003) for _ in range(T)]
    mat = {"good": good}
    for i in range(5):
        mat[f"bad{i}"] = [rng.gauss(0, 0.01) for _ in range(T)]
    r = cscv_pbo(mat, n_splits=8)
    assert r.pbo < 0.1


def test_pbo_pure_noise_set_is_well_above_a_robust_set() -> None:
    # No real edge: the IS-best is OS-indeterminate -> PBO materially above a robust set's ~0
    # (the exact value has sampling variance; the SIGNAL is "much higher than robust").
    rng = random.Random(13)
    T = 160
    noise = {f"c{i}": [rng.gauss(0, 0.01) for _ in range(T)] for i in range(10)}
    pbo_noise = cscv_pbo(noise, n_splits=8).pbo

    rng2 = random.Random(14)
    robust = {"good": [0.01 + rng2.gauss(0, 0.003) for _ in range(T)]}
    for i in range(9):
        robust[f"bad{i}"] = [rng2.gauss(0, 0.01) for _ in range(T)]
    pbo_robust = cscv_pbo(robust, n_splits=8).pbo

    assert pbo_noise > 0.2
    assert pbo_noise > pbo_robust + 0.2


def test_pbo_adversarial_overfit_set_is_high() -> None:
    # Construct configs that are deliberately IS-best-but-OS-worst: each config spikes in the
    # FIRST half and craters in the SECOND half (contiguous blocks). IS-best (first-half spike)
    # is reliably OS-worst -> PBO -> 1.
    T = 160
    half = T // 2
    mat: dict[str, list[float]] = {}
    for i in range(6):
        spike = 0.05 + 0.001 * i  # distinct first-half spikes -> a clear IS winner per slice
        series = [spike] * half + [-spike] * (T - half)
        mat[f"c{i}"] = series
    r = cscv_pbo(mat, n_splits=8)
    assert r.pbo > 0.8


def test_pbo_requires_even_splits() -> None:
    mat = {"a": [0.0] * 64, "b": [0.0] * 64}
    with pytest.raises(ValueError):
        cscv_pbo(mat, n_splits=7)


def test_pbo_requires_two_configs() -> None:
    with pytest.raises(ValueError):
        cscv_pbo({"only": [0.01] * 64}, n_splits=8)


def test_pbo_requires_uniform_series_length() -> None:
    with pytest.raises(ValueError):
        cscv_pbo({"a": [0.0] * 64, "b": [0.0] * 60}, n_splits=8)
