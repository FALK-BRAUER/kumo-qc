"""DSR tests (#323 B.1) — known-case math, monotonicity, noise/strong limits.

Synthetic returns fixtures only — ZERO backtest.
"""
from __future__ import annotations

import math

import pytest

from sweeps.objective.dsr import (
    EULER_MASCHERONI,
    _norm_cdf,
    _norm_ppf,
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe,
    sharpe_ratio,
)


def test_norm_cdf_known_values() -> None:
    assert _norm_cdf(0.0) == pytest.approx(0.5)
    assert _norm_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert _norm_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


def test_norm_ppf_is_cdf_inverse() -> None:
    for p in (0.025, 0.1, 0.5, 0.9, 0.975):
        assert _norm_cdf(_norm_ppf(p)) == pytest.approx(p, abs=1e-6)


def test_norm_ppf_rejects_out_of_domain() -> None:
    with pytest.raises(ValueError):
        _norm_ppf(0.0)
    with pytest.raises(ValueError):
        _norm_ppf(1.0)


def test_sharpe_ratio_known_case() -> None:
    # mean 0.01, the series below has a hand-checkable mean/std.
    rets = [0.02, 0.00, 0.02, 0.00]  # mean 0.01, var 0.0001, std 0.01 -> SR 1.0
    assert sharpe_ratio(rets) == pytest.approx(1.0)


def test_expected_max_sharpe_n1_is_zero() -> None:
    # A single trial has no multiple-comparisons inflation.
    assert expected_max_sharpe(1, 0.25) == 0.0


def test_expected_max_sharpe_golden_value() -> None:
    # SR_0 = sqrt(var) * [(1-g) Phi^-1(1-1/N) + g Phi^-1(1-1/(N e))], N=10, var=0.04.
    n, var = 10, 0.04
    g = EULER_MASCHERONI
    expected = math.sqrt(var) * (
        (1 - g) * _norm_ppf(1 - 1 / n) + g * _norm_ppf(1 - 1 / (n * math.e))
    )
    assert expected_max_sharpe(n, var) == pytest.approx(expected, rel=1e-9)


def test_expected_max_sharpe_increases_with_n() -> None:
    # More trials -> higher luck bar.
    vals = [expected_max_sharpe(n, 0.04) for n in (2, 10, 100, 1000)]
    assert vals == sorted(vals)
    assert all(b > a for a, b in zip(vals, vals[1:]))


def test_dsr_decreases_as_n_trials_rises() -> None:
    # The multiple-comparisons correction BITES: same series, more trials -> lower DSR.
    # Use a MODERATE-edge, short series so PSR sits off the 0/1 saturation rails and the
    # rising SR_0 benchmark visibly pushes DSR down.
    import random

    random.seed(101)
    rets = [random.gauss(0.0015, 0.01) for _ in range(60)]  # weak edge, short track
    dsr_low = deflated_sharpe(rets, n_trials=2, sharpe_variance_across_trials=0.25)
    dsr_high = deflated_sharpe(rets, n_trials=5000, sharpe_variance_across_trials=0.25)
    assert dsr_low > dsr_high


def test_dsr_strong_stable_series_n1_approaches_one() -> None:
    # A clearly-positive low-variance series at N=1 (no deflation) -> ~1.
    rets = [0.01, 0.011, 0.009, 0.012, 0.008] * 40  # SR high, T=200
    dsr = deflated_sharpe(rets, n_trials=1, sharpe_variance_across_trials=0.0)
    assert dsr > 0.99


def test_dsr_pure_noise_series_collapses_toward_half_or_below() -> None:
    # A zero-mean noise series has no edge -> PSR vs a positive SR_0 is low.
    import random

    random.seed(7)
    rets = [random.gauss(0.0, 0.01) for _ in range(300)]
    dsr = deflated_sharpe(rets, n_trials=100, sharpe_variance_across_trials=0.04)
    assert dsr < 0.6


def test_probabilistic_sharpe_against_zero_benchmark_known_sign() -> None:
    # A positive-Sharpe series vs benchmark 0 -> PSR > 0.5; vs a benchmark above its SR -> < 0.5.
    rets = [0.02, 0.00, 0.02, 0.00] * 50  # SR ~1.0
    assert probabilistic_sharpe(rets, 0.0) > 0.5
    assert probabilistic_sharpe(rets, 2.0) < 0.5
