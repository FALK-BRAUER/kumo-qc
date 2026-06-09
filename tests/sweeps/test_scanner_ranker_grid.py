from __future__ import annotations

from pathlib import Path

from build.sweep_build import build_sweep_dist, sweep_to_strategy_config
from sweeps.grids.scanner_ranker import BASE_MODULE, first_pack


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


def test_top20_variant_maps_ranker_runtime_and_phase() -> None:
    variant = next(item for item in first_pack() if item.variant_id == "scanner_lambdamart_top20")

    cfg = sweep_to_strategy_config(variant.config, base_module=BASE_MODULE)

    ranking = cfg.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"
    assert cfg.runtime.scanner_ranker_enabled is True
    assert cfg.runtime.scanner_ranker_top_x == 20
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
