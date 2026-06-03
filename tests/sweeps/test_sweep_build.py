"""#323 prod-bridge — SweepConfig → StrategyConfig → dist (build/sweep_build.py).

The load-bearing wiring: a deploy/marker bug = the WRONG config gets tested; a silent hook
no-op = fabricated axis coverage (the W5-mirage class). These pin: the swept kinds override
the base correctly, the entry_selection GUARD (PreFlightStaleness) survives, the algorithm
impl-swap remaps logical→field names, the regime spy/vix split is correct, and every unbuilt
hook (entries_cap, lower_wick_booster) FAILS LOUD rather than building a silent no-op.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from build.sweep_build import (
    UnsupportedSweepAxisError,
    build_sweep_dist,
    sweep_to_strategy_config,
)
from sweeps.grids.intraday_selectivity import enumerate_grid
from sweeps.types import PhaseChoice, SweepConfig

COARSE = enumerate_grid(coarse=True).configs


def _cap_of(c: SweepConfig):
    return dict(next(ch for ch in c.choices if ch.kind == "sizing").params).get("entries_cap")


def _algo_of(c: SweepConfig) -> str:
    return next(ch for ch in c.choices if ch.kind == "entry_selection").impl_name


def _gap_nowick_nocap() -> SweepConfig:
    for c in COARSE:
        if _cap_of(c) is None and "gap_vol" in _algo_of(c):
            d = dict(next(ch for ch in c.choices if ch.kind == "entry_selection").params)
            if not d.get("lower_wick_booster", False):
                return c
    raise AssertionError("no runnable gap config in coarse grid")


def _hold_nocap() -> SweepConfig:
    for c in COARSE:
        if _cap_of(c) is None and "hold" in _algo_of(c):
            return c
    raise AssertionError("no runnable hold config in coarse grid")


def test_swept_kinds_override_base_others_preserved() -> None:
    cfg = sweep_to_strategy_config(_gap_nowick_nocap())
    # base-only kinds survive verbatim (not dropped by the merge)
    for kind in ("universe", "entry_timing", "protective_stop", "exit_hard", "diagnostics"):
        assert kind in cfg.phases, f"base kind {kind} must survive the merge"
    assert cfg.name.startswith("sweep-")
    assert cfg.is_fixture is False  # a real champion stack, never a fixture


def test_entry_selection_guard_preserved_algorithm_replaced() -> None:
    cfg = sweep_to_strategy_config(_gap_nowick_nocap())
    es = cfg.phases["entry_selection"]
    assert isinstance(es, list)
    names = [s.impl.__name__ for s in es]
    assert "PreFlightStaleness" in names, "the staleness GUARD must be preserved"
    assert any("GapVol" in n for n in names), "the swept gap algorithm must be wired"


def test_min_score_primary_axis_lands_in_built_config() -> None:
    # the PRIMARY lever must actually reach the signal phase params (not silently dropped)
    for c in COARSE:
        if _cap_of(c) is not None:
            continue
        d = dict(next(ch for ch in c.choices if ch.kind == "entry_selection").params)
        if d.get("lower_wick_booster", False):
            continue
        want = dict(next(ch for ch in c.choices if ch.kind == "signal").params)["min_score"]
        cfg = sweep_to_strategy_config(c)
        assert cfg.phases["signal"].params.min_score == want


def test_regime_spy_disabled_vix_split() -> None:
    cfg = sweep_to_strategy_config(_gap_nowick_nocap())
    regime = {s.impl.__name__: s for s in cfg.phases["regime"]}
    assert "SpySma200" in regime and regime["SpySma200"].enabled is False  # off-biased
    assert "VixPercentile" in regime  # vix slot present (params from the swept choice)


def test_vix_off_keeps_base_threshold_not_none() -> None:
    # BUG fix: the vix-OFF grid point carries threshold=None; it must NOT be written into the
    # float field (keep the base default). enabled must be off so it's inert either way.
    off = None
    for c in COARSE:
        if _cap_of(c) is not None:
            continue
        d = dict(next(ch for ch in c.choices if ch.kind == "entry_selection").params)
        if d.get("lower_wick_booster", False):
            continue
        r = dict(next(ch for ch in c.choices if ch.kind == "regime").params)
        if r.get("vix_percentile_enabled") is False:
            off = c
            break
    assert off is not None
    cfg = sweep_to_strategy_config(off)
    vix = next(s for s in cfg.phases["regime"] if s.impl.__name__ == "VixPercentile")
    assert vix.params.vix_percentile_threshold is not None  # base default preserved, not None
    assert vix.params.vix_percentile_enabled is False


def test_hold_impl_swap_remaps_hold_n_bars_to_window_bars() -> None:
    cfg = sweep_to_strategy_config(_hold_nocap())
    algo = next(s for s in cfg.phases["entry_selection"] if "Hold" in s.impl.__name__)
    # the logical axis hold_n_bars must have landed on the real field window_bars
    assert hasattr(algo.params, "window_bars")


def test_entries_cap_hook_fails_loud() -> None:
    capped = next(c for c in COARSE if _cap_of(c) is not None)
    with pytest.raises(UnsupportedSweepAxisError, match="entries_cap"):
        sweep_to_strategy_config(capped)


def test_lower_wick_booster_hook_fails_loud() -> None:
    wick = None
    for c in COARSE:
        d = dict(next(ch for ch in c.choices if ch.kind == "entry_selection").params)
        if d.get("lower_wick_booster", False) and _cap_of(c) is None:
            wick = c
            break
    if wick is None:
        pytest.skip("no gap_loud_wick config in coarse grid")
    with pytest.raises(UnsupportedSweepAxisError, match="lower_wick_booster"):
        sweep_to_strategy_config(wick)


def test_build_sweep_dist_emits_marker(tmp_path: Path) -> None:
    c = _gap_nowick_nocap()
    r = build_sweep_dist(c, dist_dir=tmp_path / "d")
    assert r.config_hash
    main = (tmp_path / "d" / "main.py").read_text()
    assert f"sweep-{c.config_hash}" in main, "deploy marker (config.name) must be in main.py"


def test_unknown_swept_field_fails_loud() -> None:
    # a grid-axis/phase-field naming drift (a param that isn't a real field) must NOT silently pass
    bad = SweepConfig(choices=(
        PhaseChoice(kind="signal", impl_name="bct_score_full",
                    params=(("not_a_real_field", 9),), free_params=1),
    ))
    with pytest.raises(UnsupportedSweepAxisError, match="naming drift|not fields"):
        sweep_to_strategy_config(bad)


def test_exit_target_profit_take_lands_not_dropped() -> None:
    # #364 R2 regression: a swept exit_target/profit_take choice MUST land. The codegen had no
    # exit_target handler → the choice was SILENTLY DROPPED and R2 cells ran R1-C-only (false result).
    cfg = sweep_to_strategy_config(SweepConfig(choices=(
        PhaseChoice("exit_target", "profit_take",
                    (("mode", "tenkan_ratchet"), ("enabled", True)), 0),
    ), continuous_weekly=True))
    et = cfg.phases.get("exit_target")
    assert et is not None, "exit_target choice silently dropped (the R2 codegen bug)"
    slot = et[0] if isinstance(et, list) else et
    assert slot.impl.__name__ == "ProfitTake"
    assert slot.params.mode == "tenkan_ratchet" and slot.enabled is True


def test_swept_kind_without_handler_fails_loud() -> None:
    # Structural guard (generalizes the R2 exit_target silent-drop): a swept PhaseChoice whose kind
    # has NO handler in sweep_to_strategy_config MUST raise, not silently drop → no phantom-correct dist.
    bogus = SweepConfig(choices=(
        PhaseChoice("portfolio_risk", "gross_exposure_cap", (("enabled", True),), 0),
    ), continuous_weekly=True)
    with pytest.raises(UnsupportedSweepAxisError, match="NO handler"):
        sweep_to_strategy_config(bogus)
