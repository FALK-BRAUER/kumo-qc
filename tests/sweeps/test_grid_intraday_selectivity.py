"""Grid enumerator tests (#323) — cardinality, dry-run, determinism, dedup, axis pruning.

Refined grid (order-density mine + HQ): PRIMARY axis = signal min_score {6,7,8}; gap
de-emphasised {0.03,0.04}; entries_cap is a clean hook axis on the sizing phase; regime via
vix_percentile. ZERO backtest — the enumerator only BUILDS SweepConfigs.
"""
from __future__ import annotations

from sweeps.grids.intraday_selectivity import (
    ALGORITHM_AXIS,
    MIN_SCORE_AXIS,
    GridAxes,
    dry_run,
    enumerate_grid,
)
from sweeps.grids.windows_fy2025 import (
    FY2024_OOS,
    FY2025_PANEL,
    WINDOW_ROLES,
    sweep_windows,
)
from sweeps.types import SweepConfig


def test_full_cardinality() -> None:
    full = enumerate_grid()
    # min_score{3} x ( gap algos(2): gap{2}xvol{4}=8 ea -> 16 ; hold(1): hold{3}xvol{4}=12 )
    #             x entries_cap{4} x vix{3} x spy{2}
    per_algo = (2 * (2 * 4)) + (3 * 4)  # 16 + 12 = 28
    assert full.cardinality == 3 * per_algo * 4 * 3 * 2 == 2016
    assert full.coarse is False


def test_coarse_cardinality_is_the_first_pass_subset() -> None:
    coarse = enumerate_grid(coarse=True)
    # min_score{2} x ( gap(2): gap{1}xvol{2}=2 ea ->4 ; hold(1): hold{2}xvol{2}=4 )
    #             x cap{2} x vix{2} x spy{1}
    per_algo = (2 * (1 * 2)) + (2 * 2)  # 4 + 4 = 8
    assert coarse.cardinality == 2 * per_algo * 2 * 2 * 1 == 64
    assert coarse.coarse is True


def test_min_score_is_the_primary_axis() -> None:
    assert MIN_SCORE_AXIS == (6, 7, 8)
    full = enumerate_grid()
    seen_scores = set()
    for cfg in full.configs:
        sig = next(c for c in cfg.choices if c.kind == "signal")
        assert sig.impl_name == "bct_score_full"
        seen_scores.add(dict(sig.params)["min_score"])
    assert seen_scores == {6, 7, 8}


def test_enumeration_is_deterministic_and_deduped() -> None:
    a = enumerate_grid()
    b = enumerate_grid()
    hashes_a = [c.config_hash for c in a.configs]
    hashes_b = [c.config_hash for c in b.configs]
    assert hashes_a == hashes_b  # byte-identical order
    assert len(set(hashes_a)) == len(hashes_a)  # no duplicate configs


def test_every_config_wires_the_four_phase_kinds() -> None:
    full = enumerate_grid()
    for cfg in full.configs:
        kinds = {c.kind for c in cfg.choices}
        assert kinds == {"signal", "entry_selection", "sizing", "regime"}


def test_reclaim_cross_is_never_enumerated() -> None:
    full = enumerate_grid()
    impls = {c.impl_name for cfg in full.configs for c in cfg.choices}
    assert not any("reclaim" in name for name in impls)
    assert set(ALGORITHM_AXIS) == {"gap_loud", "hold_above_n", "gap_loud_wick"}


def test_gap_de_emphasised_to_two_points() -> None:
    full = enumerate_grid()
    gaps = set()
    for cfg in full.configs:
        entry = next(c for c in cfg.choices if c.kind == "entry_selection")
        if "gap_threshold" in entry.param_dict():
            gaps.add(entry.param_dict()["gap_threshold"])
    assert gaps == {0.03, 0.04}


def test_gap_algos_carry_gap_hold_algo_carries_hold_bars() -> None:
    full = enumerate_grid()
    saw_gap = saw_hold = saw_wick = False
    for cfg in full.configs:
        entry = next(c for c in cfg.choices if c.kind == "entry_selection")
        params = entry.param_dict()
        if entry.impl_name == "bct_intraday_hold_confirm":
            assert "hold_n_bars" in params and "gap_threshold" not in params
            saw_hold = True
        else:
            assert "gap_threshold" in params and "hold_n_bars" not in params
            saw_gap = True
            if params.get("lower_wick_booster") is True:
                saw_wick = True
    assert saw_gap and saw_hold and saw_wick


def test_entries_cap_is_a_clean_hook_on_the_sizing_phase() -> None:
    full = enumerate_grid()
    caps = set()
    for cfg in full.configs:
        sizing = next(c for c in cfg.choices if c.kind == "sizing")
        assert sizing.impl_name == "flat_pct_heatcap"
        caps.add(dict(sizing.params)["entries_cap"])
    assert caps == {None, 10, 15, 20}  # off + the three caps


def test_regime_uses_vix_percentile_with_off_bias() -> None:
    full = enumerate_grid()
    for cfg in full.configs:
        regime = next(c for c in cfg.choices if c.kind == "regime")
        assert regime.impl_name == "vix_percentile"
        p = dict(regime.params)
        # off -> enabled False / threshold None; on -> enabled True / threshold set.
        if p["vix_percentile_enabled"]:
            assert p["vix_percentile_threshold"] in (75.0, 50.0)
        else:
            assert p["vix_percentile_threshold"] is None


def test_single_candidate_axis_costs_zero_dof() -> None:
    fixed = enumerate_grid(
        GridAxes(
            min_score=(7,), algorithms=("gap_loud",), gap_pct=(0.03,), vol_ratio=(1.0,),
            hold_n_bars=(3,), entries_cap=(None,), vix_gate=(None,), spy_200ma=(False,),
        )
    )
    assert fixed.cardinality == 1
    assert fixed.configs[0].total_free_params == 0  # nothing swept

    swept = enumerate_grid(
        GridAxes(
            min_score=(6, 7, 8), algorithms=("gap_loud",), gap_pct=(0.03, 0.04),
            vol_ratio=(1.0,), hold_n_bars=(3,), entries_cap=(None,), vix_gate=(None,),
            spy_200ma=(False,),
        )
    )
    # min_score swept (1) + gap swept (1) = 2 free params on every variant.
    assert all(c.total_free_params == 2 for c in swept.configs)


def test_dry_run_lists_every_config_and_states_the_count() -> None:
    coarse = enumerate_grid(coarse=True)
    text = dry_run(coarse)
    header, *body = text.strip().splitlines()
    assert "COARSE" in header and str(coarse.cardinality) in header
    assert len(body) == coarse.cardinality
    for cfg in coarse.configs:
        assert cfg.config_hash in text


def test_configs_are_sweepconfig_instances_the_protocol_consumes() -> None:
    full = enumerate_grid()
    assert all(isinstance(c, SweepConfig) for c in full.configs)
    assert all(isinstance(c.total_free_params, int) for c in full.configs)


# --- the #323 window panel (FY2025 bi-monthly + FY2024 OOS) --- #
def test_sweep_round_windows_are_the_six_fy2025_bimonthly() -> None:
    windows = sweep_windows()
    assert len(windows) == 6
    assert windows == FY2025_PANEL
    assert windows[0].start == "2025-01-01" and windows[-1].end == "2025-12-31"


def test_holdout_is_excluded_from_a_round_included_only_at_final() -> None:
    assert FY2024_OOS not in sweep_windows()
    final = sweep_windows(include_holdout=True)
    assert final[-1] == FY2024_OOS and len(final) == 7


def test_window_roles_tag_panel_vs_holdout() -> None:
    assert all(WINDOW_ROLES[w.name] == "panel" for w in FY2025_PANEL)
    assert WINDOW_ROLES[FY2024_OOS.name] == "holdout"
