"""ADR-D5 scoring tests (#214 component 5).

The headline test: rank-by-STABILITY-not-PEAK — a high-peak / high-variance config scores
BELOW a steady one. Plus: stability = mean/std, complexity penalty applied, DoF budget flag.
"""
from __future__ import annotations

import pytest

from sweeps.aggregate import aggregate
from sweeps.score import (
    COMPLEXITY_WEIGHT,
    ROBUSTNESS_WEIGHT,
    STD_FLOOR,
    complexity_penalty,
    robustness_penalty,
    score,
    stability,
)
from sweeps.types import ConfigRun, PhaseChoice, ResultMetrics, SweepConfig, Window, WindowResult


def _config(*, free_params: int = 1, hash_salt: str = "a") -> SweepConfig:
    return SweepConfig(
        choices=(PhaseChoice("signal", "Mock", ((hash_salt, 1),), free_params),)
    )


def _run(sharpes: list[float], *, free_params: int = 1, salt: str = "a") -> ConfigRun:
    wrs = tuple(
        WindowResult(
            window=Window(name=f"w{i}", start="", end=""),
            metrics=ResultMetrics(sharpe=s, ret_pct=s * 5, dd_pct=10.0, orders=10),
        )
        for i, s in enumerate(sharpes)
    )
    return ConfigRun(config=_config(free_params=free_params, hash_salt=salt), window_results=wrs)


def test_stability_is_mean_over_std() -> None:
    agg = aggregate(_run([2, 4, 4, 4, 5, 5, 7, 9]))  # mean 5, std 2
    assert stability(agg) == pytest.approx(5.0 / 2.0)


def test_stability_std_floored_for_flat_config() -> None:
    # Perfectly flat (std 0) -> floored at STD_FLOOR, finite not infinite.
    agg = aggregate(_run([3, 3, 3, 3, 3, 3]))
    assert stability(agg) == pytest.approx(3.0 / STD_FLOOR)


def test_complexity_penalty_proportional_to_dof() -> None:
    assert complexity_penalty(0) == 0.0
    assert complexity_penalty(8) == pytest.approx(COMPLEXITY_WEIGHT * 8)


def test_robustness_penalty_proportional_to_sharpe_std() -> None:
    agg = aggregate(_run([2, 4, 4, 4, 5, 5, 7, 9]))  # std 2
    assert robustness_penalty(agg) == pytest.approx(ROBUSTNESS_WEIGHT * 2.0)


def test_composite_subtracts_both_penalties() -> None:
    agg = aggregate(_run([2, 4, 4, 4, 5, 5, 7, 9], free_params=3))  # mean 5, std 2
    s = score(agg)
    expected = (5.0 / 2.0) - complexity_penalty(3) - robustness_penalty(agg)
    assert s.composite == pytest.approx(expected)
    assert s.stability == pytest.approx(5.0 / 2.0)
    assert s.total_free_params == 3


def test_rank_by_stability_not_peak() -> None:
    """THE D5.2 demonstration: a high-PEAK high-VARIANCE config ranks BELOW a steady one.

    - peaky:  windows [0, 0, 0, 0, 0, 12]  -> mean 2.0, BEST window 12 (highest peak), high std
    - steady: windows [3, 3, 3, 3, 3, 3]   -> mean 3.0, best window only 3, ~zero std

    Ranking by best-window Sharpe would pick `peaky` (peak 12 >> 3). Ranking by STABILITY
    (mean/std) picks `steady`. The composite must rank steady ABOVE peaky.
    """
    peaky = aggregate(_run([0, 0, 0, 0, 0, 12], salt="peaky"))
    steady = aggregate(_run([3, 3, 3, 3, 3, 3], salt="steady"))

    # Sanity: peaky genuinely has the higher single-window PEAK.
    assert peaky.sharpe.maximum > steady.sharpe.maximum

    s_peaky = score(peaky)
    s_steady = score(steady)

    # Yet steady wins on the composite (stability beats peak).
    assert s_steady.composite > s_peaky.composite
    # And specifically because stability dominates.
    assert s_steady.stability > s_peaky.stability


def test_complexity_penalty_breaks_a_stability_tie_toward_simpler() -> None:
    # Two configs with IDENTICAL window distributions but different DoF -> simpler wins.
    simple = aggregate(_run([2, 4, 4, 4, 5, 5, 7, 9], free_params=1, salt="simple"))
    complex_ = aggregate(_run([2, 4, 4, 4, 5, 5, 7, 9], free_params=6, salt="complex"))
    s_simple = score(simple)
    s_complex = score(complex_)
    assert s_simple.stability == pytest.approx(s_complex.stability)  # same raw alpha
    assert s_simple.composite > s_complex.composite  # Occam: simpler wins


def test_dof_budget_flag() -> None:
    over = score(aggregate(_run([1, 1, 1, 1, 1, 1], free_params=9)), dof_budget=8)
    under = score(aggregate(_run([1, 1, 1, 1, 1, 1], free_params=4)), dof_budget=8)
    assert over.over_dof_budget is True
    assert under.over_dof_budget is False
