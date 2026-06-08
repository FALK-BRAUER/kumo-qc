from __future__ import annotations

import pytest

from build.sweep_build import UnsupportedSweepAxisError, sweep_to_strategy_config
from sweeps.types import PhaseChoice, SweepConfig


def _choice(**kwargs: object) -> PhaseChoice:
    return PhaseChoice(
        kind="ranking",
        impl_name="george_industry_attention",
        params=(),
        free_params=0,
        **kwargs,
    )


def test_phase_choice_enabled_true_keeps_hash_default_compatible() -> None:
    assert SweepConfig(choices=(_choice(),)).config_hash == SweepConfig(
        choices=(_choice(enabled=True),)
    ).config_hash


def test_phase_choice_disabled_moves_hash() -> None:
    assert SweepConfig(choices=(_choice(enabled=False),)).config_hash != SweepConfig(
        choices=(_choice(),)
    ).config_hash


def test_runtime_overrides_move_hash_deterministically() -> None:
    left = SweepConfig(
        choices=(),
        runtime_overrides=(
            ("watchlist_carry_max", 10),
            ("security_profile_source", "profiles.csv"),
        ),
    )
    right = SweepConfig(
        choices=(),
        runtime_overrides=(
            ("security_profile_source", "profiles.csv"),
            ("watchlist_carry_max", 10),
        ),
    )
    assert left.config_hash == right.config_hash
    assert left.config_hash != SweepConfig(choices=()).config_hash


def test_sweep_build_maps_runtime_overrides_to_strategy_config() -> None:
    sweep = SweepConfig(
        choices=(),
        continuous_weekly=True,
        warmup_days=320,
        runtime_overrides=(
            ("watchlist_carry_max", 10),
            ("security_profile_source", "data/profiles.csv"),
        ),
    )

    cfg = sweep_to_strategy_config(sweep, base_module="strategies.champion_george_context")

    assert cfg.runtime.continuous_weekly is True
    assert cfg.runtime.warmup_days == 320
    assert cfg.runtime.watchlist_carry_max == 10
    assert cfg.runtime.security_profile_source == "data/profiles.csv"


def test_sweep_build_fails_loud_on_unknown_runtime_override() -> None:
    sweep = SweepConfig(choices=(), runtime_overrides=(("not_a_runtime_field", True),))

    with pytest.raises(UnsupportedSweepAxisError, match="RuntimeConfig fields"):
        sweep_to_strategy_config(sweep, base_module="strategies.champion_george_context")


def test_sweep_build_can_disable_base_slot() -> None:
    sweep = SweepConfig(
        choices=(
            PhaseChoice(
                kind="ranking",
                impl_name="george_industry_attention",
                params=(),
                free_params=0,
                enabled=False,
            ),
        )
    )

    cfg = sweep_to_strategy_config(sweep, base_module="strategies.champion_george_context")

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.enabled is False


def test_sweep_build_can_add_trail_provider() -> None:
    sweep = SweepConfig(
        choices=(
            PhaseChoice(
                kind="trail",
                impl_name="position_path_tracker",
                params=(),
                free_params=0,
            ),
        )
    )

    cfg = sweep_to_strategy_config(sweep, base_module="strategies.champion_george_context")

    trail = cfg.phases["trail"]
    assert not isinstance(trail, list)
    assert trail.impl.__name__ == "PositionPathTracker"
