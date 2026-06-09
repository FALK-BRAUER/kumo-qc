from __future__ import annotations

from pathlib import Path

from build.sweep_build import build_sweep_dist, sweep_to_strategy_config
from sweeps.grids.scanner_ranker import BASE_MODULE, all_variants, first_pack, top_x_expansion_pack


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


def test_top20_variant_maps_ranker_runtime_and_phase() -> None:
    variant = next(item for item in first_pack() if item.variant_id == "scanner_lambdamart_top20")

    cfg = sweep_to_strategy_config(variant.config, base_module=BASE_MODULE)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 20
    assert cfg.runtime.scanner_ranker_model_path == "objectstore://bct_lambdamart_qc_safe_v1.json"


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
