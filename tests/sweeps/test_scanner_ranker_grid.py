from __future__ import annotations

import json
from pathlib import Path

from build.sweep_build import build_sweep_dist, sweep_to_strategy_config
from sweeps.grids.scanner_ranker import (
    BASE_MODULE,
    DEFAULT_OPPORTUNITY_ARTIFACT_PATH,
    DEFAULT_OPPORTUNITY_MODEL_KEY,
    REAL_STRATEGY_BASES,
    all_variants,
    first_pack,
    opportunity_ranker_pack,
    rank_aware_intraday_pack,
    rank_aware_sizing_pack,
    rank_history_requalification_pack,
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


def test_rank_aware_sizing_pack_shape() -> None:
    variants = rank_aware_sizing_pack()

    assert len(variants) == 8
    assert [variant.variant_id for variant in variants] == [
        "ranksize_top20_flat_control",
        "ranksize_top20_balanced",
        "ranksize_top20_concentrated",
        "ranksize_top20_de_risked",
        "ranksize_top50_flat_control",
        "ranksize_top50_balanced",
        "ranksize_top50_tail_tiny",
        "ranksize_top50_top_heavy",
    ]
    assert {variant.wave for variant in variants} == {5}
    assert {variant.config.runtime_dict()["scanner_ranker_top_x"] for variant in variants} == {20, 50}
    assert len({variant.variant_id for variant in all_variants()}) == len(all_variants())


def test_opportunity_ranker_pack_shape() -> None:
    variants = opportunity_ranker_pack()

    assert len(variants) == 6
    assert [variant.variant_id for variant in variants] == [
        "opportunity_champion_baseline",
        "opportunity_linear_top10",
        "opportunity_linear_top20",
        "opportunity_linear_top50",
        "opportunity_linear_top20_rankaware_entry",
        "opportunity_linear_top20_giveback35_exit",
    ]
    assert {variant.wave for variant in variants} == {6}
    assert {variant.config.runtime_dict().get("scanner_ranker_model_path") for variant in variants[1:]} == {
        DEFAULT_OPPORTUNITY_MODEL_KEY
    }
    assert {variant.local_artifact_path for variant in variants[1:]} == {str(DEFAULT_OPPORTUNITY_ARTIFACT_PATH)}
    assert len({variant.variant_id for variant in all_variants()}) == len(all_variants())


def test_rank_history_requalification_pack_shape() -> None:
    variants = rank_history_requalification_pack()

    assert len(variants) == 18
    assert [variant.variant_id for variant in variants[:6]] == [
        "giveback_no_bull_rh_off",
        "giveback_no_bull_rh_dynamic_score_medium",
        "giveback_no_bull_rh_requal_core50",
        "giveback_no_bull_rh_requal_entry",
        "giveback_no_bull_rh_requal_sizing",
        "giveback_no_bull_rh_requal_entry_sizing",
    ]
    assert {variant.wave for variant in variants} == {7}
    assert {variant.base_module for variant in variants} == {
        base_module for _, base_module, _ in REAL_STRATEGY_BASES
    }
    history_variants = [variant for variant in variants if "rh_requal" in variant.variant_id]
    assert len(history_variants) == 12
    assert {variant.config.runtime_dict()["scanner_ranker_top_x"] for variant in history_variants} == {0}
    assert all(
        next(choice for choice in variant.config.choices if choice.kind == "ranking").param_dict()[
            "scanner_rank_history_enabled"
        ]
        is True
        for variant in history_variants
    )
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


def test_rank_aware_sizing_variant_swaps_sizer_only() -> None:
    variant = next(
        item
        for item in rank_aware_sizing_pack()
        if item.variant_id == "ranksize_top50_tail_tiny"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    sizing = cfg.phases["sizing"]
    assert not isinstance(sizing, list)
    assert sizing.impl.__name__ == "RankAwareHeatcap"
    assert sizing.params.top_multiplier == 1.20
    assert sizing.params.mid_multiplier == 0.80
    assert sizing.params.tail_multiplier == 0.20
    entries = cfg.phases["entry_selection"]
    assert [slot.impl.__name__ for slot in entries] == ["PreFlightStaleness", "BctIntradayGapVolConfirm"]
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 50


def test_rank_aware_sizing_control_keeps_flat_sizer() -> None:
    variant = next(
        item
        for item in rank_aware_sizing_pack()
        if item.variant_id == "ranksize_top20_flat_control"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    sizing = cfg.phases["sizing"]
    assert not isinstance(sizing, list)
    assert sizing.impl.__name__ == "FlatPctHeatcap"
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 20


def test_opportunity_top20_variant_maps_linear_artifact_runtime() -> None:
    variant = next(item for item in opportunity_ranker_pack() if item.variant_id == "opportunity_linear_top20")

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 20
    assert cfg.runtime.scanner_ranker_model_path == DEFAULT_OPPORTUNITY_MODEL_KEY


def test_opportunity_rankaware_variant_preserves_preflight() -> None:
    variant = next(
        item for item in opportunity_ranker_pack() if item.variant_id == "opportunity_linear_top20_rankaware_entry"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    entries = cfg.phases["entry_selection"]
    assert [slot.impl.__name__ for slot in entries] == ["PreFlightStaleness", "RankAwareGapConfirm"]
    assert cfg.runtime.scanner_ranker_model_path == DEFAULT_OPPORTUNITY_MODEL_KEY


def test_opportunity_giveback35_variant_composes_trail_and_exit() -> None:
    variant = next(
        item for item in opportunity_ranker_pack() if item.variant_id == "opportunity_linear_top20_giveback35_exit"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    trail = cfg.phases["trail"]
    exits = cfg.phases["exit_hard"]
    assert not isinstance(trail, list)
    assert trail.impl.__name__ == "PositionPathTracker"
    assert [slot.impl.__name__ for slot in exits] == ["CloudAdherenceTrail", "MfeIntradayExit"]
    assert exits[1].params.min_mfe_pct == 0.08
    assert exits[1].params.giveback_fraction == 0.35
    assert exits[1].params.min_giveback_pct == 0.0
    assert exits[1].params.diagnostic_log is True


def test_rank_history_variant_maps_history_params_without_top_x_gate() -> None:
    variant = next(
        item
        for item in rank_history_requalification_pack()
        if item.variant_id == "target08_let_run_rh_requal_core50"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"
    assert ranking.params.scanner_rank_history_enabled is True
    assert ranking.params.scanner_rank_history_focus_rank == 10
    assert ranking.params.scanner_rank_history_core_rank == 50
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 0


def test_rank_history_entry_sizing_variant_composes_existing_rank_aware_phases() -> None:
    variant = next(
        item
        for item in rank_history_requalification_pack()
        if item.variant_id == "target04_fast_take_rh_requal_entry_sizing"
    )

    cfg = sweep_to_strategy_config(variant.config, base_module=variant.base_module)

    entries = cfg.phases["entry_selection"]
    sizing = cfg.phases.get("sizing")
    intraday_sizing = cfg.phases["intraday_sizing"]
    assert [slot.impl.__name__ for slot in entries] == ["RankAwareGapConfirm"]
    assert sizing is None
    assert not isinstance(intraday_sizing, list)
    assert intraday_sizing.impl.__name__ == "RankAwareHeatcap"
    assert intraday_sizing.impl.PHASE_KIND == "intraday_sizing"
    assert cfg.runtime.scanner_ranker_top_x == 0


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


def test_opportunity_ranker_dist_build_emits_cloud_attrs(tmp_path: Path) -> None:
    variant = next(item for item in opportunity_ranker_pack() if item.variant_id == "opportunity_linear_top20")

    result = build_sweep_dist(variant.config, dist_dir=tmp_path / "dist", base_module=variant.base_module)
    main = (tmp_path / "dist" / "main.py").read_text(encoding="utf-8")

    assert result.config_hash
    assert "LambdamartScannerRanker" in main
    assert "SCANNER_RANKER_ENABLED = True" in main
    assert "SCANNER_RANKER_TOP_X = 20" in main
    assert f"SCANNER_RANKER_MODEL_PATH = '{DEFAULT_OPPORTUNITY_MODEL_KEY}'" in main


def test_rank_history_entry_sizing_dist_replaces_intraday_sizer(tmp_path: Path) -> None:
    variant = next(
        item
        for item in rank_history_requalification_pack()
        if item.variant_id == "giveback_no_bull_rh_requal_entry_sizing"
    )

    result = build_sweep_dist(variant.config, dist_dir=tmp_path / "dist", base_module=variant.base_module)
    manifest = json.loads((tmp_path / "dist" / "_manifest.json").read_text(encoding="utf-8"))

    assert result.config_hash
    assert "phase_intraday_sizing_rank_aware_heatcap.py" in manifest["files"]
    assert "phase_intraday_sizing_stub_intraday_sizer.py" not in manifest["files"]
    assert manifest["phase_markers"]["intraday_sizing"] == "intraday_rank_aware_heatcap_v1"
    assert "sizing" not in manifest["phase_markers"]
