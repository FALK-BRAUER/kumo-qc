from __future__ import annotations

from pathlib import Path

from build.sweep_build import build_sweep_dist, sweep_to_strategy_config
from sweeps.grids.george_context import BASE_MODULE, all_variants, six_pack, thirty_pack


def test_george_six_pack_has_expected_shape() -> None:
    variants = six_pack()

    assert len(variants) == 6
    assert {v.wave for v in variants} == {0}
    assert {v.variant_id for v in variants} == {
        "gctx_baseline_no_george",
        "gctx_industry_only",
        "gctx_attention_only",
        "gctx_watchlist_carry_only",
        "gctx_industry_watchlist",
        "gctx_full",
    }


def test_george_thirty_pack_is_five_waves_of_six() -> None:
    variants = thirty_pack()

    assert len(variants) == 30
    for wave in range(1, 6):
        assert sum(1 for v in variants if v.wave == wave) == 6
    assert {v.family for v in variants} == {
        "industry_warmup",
        "watchlist_carry",
        "george_attention",
        "entry_confirmation",
        "exit_management",
    }


def test_george_variants_have_unique_ids_and_hashes() -> None:
    variants = all_variants()

    assert len({v.variant_id for v in variants}) == len(variants)
    assert len({v.config_hash for v in variants}) == len(variants)


def test_george_baseline_disables_context_slots() -> None:
    variant = next(v for v in six_pack() if v.variant_id == "gctx_baseline_no_george")

    cfg = sweep_to_strategy_config(variant.config, base_module=BASE_MODULE)

    rebalance = cfg.phases["rebalance"]
    ranking = cfg.phases["ranking"]
    assert not isinstance(rebalance, list)
    assert not isinstance(ranking, list)
    assert rebalance.enabled is False
    assert ranking.enabled is False


def test_george_full_maps_runtime_sources_and_carry() -> None:
    variant = next(v for v in six_pack() if v.variant_id == "gctx_full")

    cfg = sweep_to_strategy_config(variant.config, base_module=BASE_MODULE)

    assert cfg.runtime.continuous_weekly is True
    assert cfg.runtime.warmup_days == 320
    assert cfg.runtime.watchlist_carry_max == 10
    assert cfg.runtime.security_profile_source
    assert cfg.runtime.george_attention_source


def test_george_full_dist_build_emits_runtime_attrs(tmp_path: Path) -> None:
    variant = next(v for v in six_pack() if v.variant_id == "gctx_full")

    result = build_sweep_dist(variant.config, dist_dir=tmp_path / "dist", base_module=BASE_MODULE)
    main = (tmp_path / "dist" / "main.py").read_text(encoding="utf-8")

    assert result.config_hash
    assert "WATCHLIST_CARRY_MAX = 10" in main
    assert "SECURITY_PROFILE_SOURCE = 'data/bluecloudtrading/runtime/security_profiles.csv'" in main
    assert "GEORGE_ATTENTION_SOURCE = 'data/bluecloudtrading/runtime/george_attention.csv'" in main


def test_george_exit_management_path_variants_build() -> None:
    for variant_id in (
        "exit_proactive_target_06",
        "exit_proactive_giveback_tight",
        "exit_scratch_flat_3d",
    ):
        variant = next(v for v in thirty_pack() if v.variant_id == variant_id)
        cfg = sweep_to_strategy_config(variant.config, base_module=BASE_MODULE)
        assert "trail" in cfg.phases
        assert "exit_hard" in cfg.phases
