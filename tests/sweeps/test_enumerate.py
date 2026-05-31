"""Enumeration tests (#214 component 1) — catalog x space() grid + DoF budget.

All on the TINY MOCK catalog (tests/sweeps/conftest). ZERO real backtest.
"""
from __future__ import annotations

import pytest

from sweeps.enumerate import (
    apply_dof_budget,
    enumerate_catalog,
    enumerate_phase,
    enumerate_product,
)
from tests.sweeps.conftest import (
    BigDoFPhase,
    MOCK_CATALOG,
    NoAxisPhase,
    OneAxisPhase,
    TwoAxisPhase,
)


def test_enumerate_phase_builds_full_cartesian_grid() -> None:
    # TwoAxisPhase: alpha in (1,2) x beta in (0.1,0.2,0.3) = 6 points.
    configs = enumerate_phase(TwoAxisPhase)  # type: ignore[arg-type]
    assert len(configs) == 6
    # Each config is a single-choice config with both axes resolved.
    param_sets = {cfg.choices[0].params for cfg in configs}
    expected = {
        (("alpha", 1), ("beta", 0.1)),
        (("alpha", 1), ("beta", 0.2)),
        (("alpha", 1), ("beta", 0.3)),
        (("alpha", 2), ("beta", 0.1)),
        (("alpha", 2), ("beta", 0.2)),
        (("alpha", 2), ("beta", 0.3)),
    }
    assert param_sets == expected


def test_enumerate_phase_params_sorted_by_field_for_determinism() -> None:
    # Fields are sorted (alpha before beta) regardless of dict order -> stable hash.
    cfg = enumerate_phase(TwoAxisPhase)[0]  # type: ignore[arg-type]
    field_names = [k for k, _ in cfg.choices[0].params]
    assert field_names == sorted(field_names)


def test_enumerate_phase_no_axes_yields_single_default_point() -> None:
    configs = enumerate_phase(NoAxisPhase)  # type: ignore[arg-type]
    assert len(configs) == 1
    assert configs[0].choices[0].params == ()
    assert configs[0].choices[0].free_params == 0


def test_free_params_matches_space_axis_count() -> None:
    configs = enumerate_phase(TwoAxisPhase)  # type: ignore[arg-type]
    assert all(c.choices[0].free_params == 2 for c in configs)
    assert all(c.total_free_params == 2 for c in configs)


def test_enumerate_catalog_flattens_each_impl_grid() -> None:
    # MOCK_CATALOG = (TwoAxisPhase[6], OneAxisPhase[3]) -> 9 single-kind configs.
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    assert len(configs) == 6 + 3
    impl_names = {c.choices[0].impl_name for c in configs}
    assert impl_names == {"TwoAxisPhase", "OneAxisPhase"}


def test_enumerate_product_cross_kind_cartesian() -> None:
    # signal points (TwoAxis 6 + OneAxis 3 = 9) x sizing points (NoAxis 1) = 9.
    configs = enumerate_product(
        [(TwoAxisPhase, OneAxisPhase), (NoAxisPhase,)]  # type: ignore[list-item]
    )
    assert len(configs) == 9
    # Each product config has exactly two choices (one per kind).
    assert all(len(c.choices) == 2 for c in configs)
    kinds = {tuple(sorted(ch.kind for ch in c.choices)) for c in configs}
    assert kinds == {("signal", "sizing")}


def test_enumerate_product_empty_catalogs() -> None:
    assert enumerate_product([]) == []


def test_config_hash_is_deterministic_and_distinct() -> None:
    configs = enumerate_phase(TwoAxisPhase)  # type: ignore[arg-type]
    hashes = [c.config_hash for c in configs]
    # All 6 grid points are distinct configs -> 6 distinct hashes.
    assert len(set(hashes)) == 6
    # Re-enumerating gives identical hashes (determinism).
    again = [c.config_hash for c in enumerate_phase(TwoAxisPhase)]  # type: ignore[arg-type]
    assert hashes == again


def test_dof_budget_keeps_in_budget_drops_over_budget() -> None:
    # Product of OneAxis(1 DoF) x BigDoF(5 DoF) = 6 DoF total per config.
    configs = enumerate_product([(OneAxisPhase,), (BigDoFPhase,)])  # type: ignore[list-item]
    assert all(c.total_free_params == 6 for c in configs)

    # Budget 5 -> all dropped (6 > 5).
    res_tight = apply_dof_budget(configs, dof_budget=5)
    assert res_tight.grid_size == 0
    assert res_tight.dropped == len(configs)
    assert all(c.total_free_params > 5 for c in res_tight.over_budget)

    # Budget 6 -> all kept (6 not > 6).
    res_ok = apply_dof_budget(configs, dof_budget=6)
    assert res_ok.grid_size == len(configs)
    assert res_ok.dropped == 0


def test_dof_budget_partial_split() -> None:
    # OneAxisPhase configs (1 DoF each) + a product giving 6 DoF each.
    small = enumerate_phase(OneAxisPhase)  # type: ignore[arg-type]  # 1 DoF each
    big = enumerate_product([(OneAxisPhase,), (BigDoFPhase,)])  # type: ignore[list-item]  # 6 DoF
    res = apply_dof_budget([*small, *big], dof_budget=3)
    assert res.grid_size == len(small)  # only the 1-DoF configs survive
    assert res.dropped == len(big)
    assert res.dof_budget == 3


def test_real_signal_catalog_enumerates_through_space() -> None:
    """TINY integration: the REAL SIGNAL_PHASES + ParamSpace flow through enumerate.

    Wires the actual src catalog (BctScoreFull, space() = min_score(3) x parabolic(4) = 12)
    through the generic enumerator — proving the mechanics consume the real contract. The RUN
    stays mocked (this test never backtests; it only builds the grid).
    """
    from phases.signal.library import SIGNAL_PHASES

    configs = enumerate_catalog(SIGNAL_PHASES)  # type: ignore[arg-type]
    # BctScoreFull space(): min_score (6,7,8) x parabolic_threshold (0.20,0.25,0.30,0.35) = 12.
    assert len(configs) == 12
    assert all(c.total_free_params == 2 for c in configs)
    assert {c.choices[0].impl_name for c in configs} == {"BctScoreFull"}
    # Hashes distinct + deterministic on the real catalog too.
    assert len({c.config_hash for c in configs}) == 12
