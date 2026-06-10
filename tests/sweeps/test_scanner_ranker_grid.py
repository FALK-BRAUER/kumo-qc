from __future__ import annotations

from pathlib import Path

from build.sweep_build import build_sweep_dist, sweep_to_strategy_config
from sweeps.grids.scanner_ranker import (
    BASE_MODULE,
    REAL_STRATEGY_BASES,
    all_variants,
    first_pack,
    rank_aware_intraday_pack,
    real_strategy_scanner_pack,
    top20_realized_exit_pack,
    top_x_expansion_pack,
)


def test_scanner_ranker_first_pack_shape() -> None:
    variants = first_pack()

    assert len(variants) == 6
    assert {variant.variant_id for variant in variants} == {
        "scanner_champion_baseline",
        "scanner_ranker_phase_off",
        "scanner_ranker_fallback_bct_order",
        "scanner_lambdamart_top10",
        "scanner_lambdamart_top20",
        "scanner_lambdamart_top50",
    }
    assert len({variant.config_hash for variant in variants}) == len(variants)


def test_scanner_ranker_top_x_expansion_pack_shape() -> None:
    variants = top_x_expansion_pack()

    assert [variant.variant_id for variant in variants] == [
        "scanner_lambdamart_top5",
        "scanner_lambdamart_top15",
        "scanner_lambdamart_top25",
        "scanner_lambdamart_top30",
        "scanner_lambdamart_top40",
        "scanner_lambdamart_top75",
    ]
    assert {variant.wave for variant in variants} == {1}
    assert len({variant.config_hash for variant in variants}) == len(variants)
    assert len({variant.variant_id for variant in all_variants()}) == len(all_variants())


def test_real_strategy_scanner_pack_shape() -> None:
    variants = real_strategy_scanner_pack()

    assert len(variants) == 12
    assert [variant.variant_id for variant in variants] == [
        "giveback_no_bull_scanner_off",
        "giveback_no_bull_scanner_top15",
        "giveback_no_bull_scanner_top20",
        "giveback_no_bull_scanner_top25",
        "target04_fast_take_scanner_off",
        "target04_fast_take_scanner_top15",
        "target04_fast_take_scanner_top20",
        "target04_fast_take_scanner_top25",
        "target08_let_run_scanner_off",
        "target08_let_run_scanner_top15",
        "target08_let_run_scanner_top20",
        "target08_let_run_scanner_top25",
    ]
    assert {variant.wave for variant in variants} == {2}
    assert {variant.base_module for variant in variants} == {
        base_module for _, base_module, _ in REAL_STRATEGY_BASES
    }
    assert BASE_MODULE not in {variant.base_module for variant in variants}
    assert len({variant.variant_id for variant in all_variants()}) == len(all_variants())


def test_top20_realized_exit_pack_shape() -> None:
    variants = top20_realized_exit_pack()

    assert len(variants) == 18
    assert [variant.variant_id for variant in variants[:6]] == [
        "giveback_no_bull_top20_base",
        "giveback_no_bull_top20_stale20",
        "giveback_no_bull_top20_stale30",
        "giveback_no_bull_top20_mfe_gb04",
        "giveback_no_bull_top20_mfe_gb06",
        "giveback_no_bull_top20_age60",
    ]
    assert {variant.wave for variant in variants} == {3}
    assert {variant.base_module for variant in variants} == {
        base_module for _, base_module, _ in REAL_STRATEGY_BASES
    }
    assert {variant.config.runtime_dict()["scanner_ranker_top_x"] for variant in variants} == {20}
    assert len({variant.variant_id for variant in all_variants()}) == len(all_variants())


def test_rank_aware_intraday_pack_shape() -> None:
    variants = rank_aware_intraday_pack()

    assert len(variants) == 8
    assert [variant.variant_id for variant in variants] == [
        "rankaware_top20_gate_control",
        "rankaware_top20_bucket_default",
        "rankaware_top20_bucket_strict_mid",
        "rankaware_top20_top5_only_loose",
        "rankaware_top50_gate_control",
        "rankaware_top50_bucket_default",
        "rankaware_top50_tail_strict",
        "rankaware_top50_mid30_tail",
    ]
    assert {variant.wave for variant in variants} == {4}
    assert {variant.config.runtime_dict()["scanner_ranker_top_x"] for variant in variants} == {20, 50}
    assert len({variant.variant_id for variant in all_variants()}) == len(all_variants())


def test_top20_variant_maps_ranker_runtime_and_phase() -> None:
    variant = next(item for item in first_pack() if item.variant_id == "scanner_lambdamart_top20")

    cfg = sweep_to_strategy_config(variant.config, base_module=BASE_MODULE)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 20
    assert cfg.runtime.scanner_ranker_model_path == "objectstore://bct_lambdamart_qc_safe_v1.json"


def test_real_strategy_top20_variant_maps_ranker_on_selected_base() -> None:
    variant = next(
        item
        for item in real_strategy_scanner_pack()
        if item.variant_id == "giveback_no_bull_scanner_top20"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 20
    assert cfg.name.startswith("sweep-")


def test_real_strategy_scanner_off_variant_keeps_base_ranking() -> None:
    variant = next(
        item
        for item in real_strategy_scanner_pack()
        if item.variant_id == "target04_fast_take_scanner_off"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "ScoreDvRanking"
    assert cfg.runtime.scanner_ranker_enabled is False


def test_top20_realized_baseline_keeps_base_exit() -> None:
    variant = next(
        item
        for item in top20_realized_exit_pack()
        if item.variant_id == "target04_fast_take_top20_base"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    exits = cfg.phases["exit_hard"]
    assert [slot.impl.__name__ for slot in exits] == ["ProactiveStrengthExit"]
    assert exits[0].params.target_pct == 0.04
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 20


def test_top20_realized_stale_variant_composes_base_exit() -> None:
    variant = next(
        item
        for item in top20_realized_exit_pack()
        if item.variant_id == "giveback_no_bull_top20_stale20"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    exits = cfg.phases["exit_hard"]
    assert [slot.impl.__name__ for slot in exits] == ["ProactiveStrengthExit", "StaleMfeExit"]
    assert exits[0].params.target_pct == 0.06
    assert exits[0].params.giveback_from_peak_pct == 0.015
    assert exits[0].params.require_still_bullish is False
    assert exits[1].params.stale_sessions == 20
    assert exits[1].params.min_hold_sessions == 20


def test_top20_realized_mfe_variant_composes_base_exit() -> None:
    variant = next(
        item
        for item in top20_realized_exit_pack()
        if item.variant_id == "target08_let_run_top20_mfe_gb04"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    exits = cfg.phases["exit_hard"]
    assert [slot.impl.__name__ for slot in exits] == ["ProactiveStrengthExit", "MfeIntradayExit"]
    assert exits[0].params.target_pct == 0.08
    assert exits[1].params.min_mfe_pct == 0.04
    assert exits[1].params.diagnostic_log is True


def test_rank_aware_variant_swaps_entry_algorithm_and_preserves_preflight() -> None:
    variant = next(
        item
        for item in rank_aware_intraday_pack()
        if item.variant_id == "rankaware_top50_tail_strict"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    entries = cfg.phases["entry_selection"]
    assert [slot.impl.__name__ for slot in entries] == ["PreFlightStaleness", "RankAwareGapConfirm"]
    assert entries[1].params.tail_gap_threshold == 0.060
    assert entries[1].params.tail_vol_mult == 1.50
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 50


def test_top25_expansion_variant_maps_ranker_runtime_and_phase() -> None:
    variant = next(item for item in top_x_expansion_pack() if item.variant_id == "scanner_lambdamart_top25")

    cfg = sweep_to_strategy_config(variant.config, base_module=BASE_MODULE)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 25
    assert cfg.runtime.scanner_ranker_model_path == "objectstore://bct_lambdamart_qc_safe_v1.json"


def test_scanner_ranker_dist_build_emits_cloud_attrs(tmp_path: Path) -> None:
    variant = next(item for item in first_pack() if item.variant_id == "scanner_lambdamart_top10")

    result = build_sweep_dist(variant.config, dist_dir=tmp_path / "dist", base_module=BASE_MODULE)
    main = (tmp_path / "dist" / "main.py").read_text(encoding="utf-8")

    assert result.config_hash
    assert "LambdamartScannerRanker" in main
    assert "SCANNER_RANKER_ENABLED = True" in main
    assert "SCANNER_RANKER_TOP_X = 10" in main
    assert "SCANNER_RANKER_MODEL_PATH = 'objectstore://bct_lambdamart_qc_safe_v1.json'" in main
