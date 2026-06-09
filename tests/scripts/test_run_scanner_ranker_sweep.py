from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.scanner_ranker import ARTIFACT_SCHEMA_VERSION, feature_contract_hash
from scripts import run_scanner_ranker_sweep as M
from sweeps.grids.scanner_ranker import first_pack


def test_variants_filters_named_subset_in_pack_order() -> None:
    args = SimpleNamespace(only="scanner_lambdamart_top20,scanner_champion_baseline", limit=None)

    variants = M._variants(args)

    assert [variant.variant_id for variant in variants] == [
        "scanner_champion_baseline",
        "scanner_lambdamart_top20",
    ]


def test_variants_rejects_unknown_id() -> None:
    args = SimpleNamespace(only="missing_variant", limit=None)

    with pytest.raises(SystemExit, match="missing_variant"):
        M._variants(args)


def test_default_artifact_required_only_for_default_model_variants(tmp_path) -> None:
    default_variants = [
        variant for variant in first_pack() if variant.variant_id == "scanner_lambdamart_top10"
    ]
    fallback_variants = [
        variant for variant in first_pack() if variant.variant_id == "scanner_ranker_fallback_bct_order"
    ]

    with pytest.raises(SystemExit, match="artifact missing"):
        M._validate_artifact(
            SimpleNamespace(
                artifact=tmp_path / "missing.json",
                allow_missing_artifact=False,
            ),
            default_variants,
        )

    artifact, artifact_hash = M._validate_artifact(
        SimpleNamespace(
            artifact=tmp_path / "missing.json",
            allow_missing_artifact=False,
        ),
        fallback_variants,
    )
    assert artifact.name == "missing.json"
    assert artifact_hash == ""


def _write_artifact(path: Path, *, feature_names: tuple[str, ...]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "model_type": "lightgbm_lambdamart_json",
                "feature_names": list(feature_names),
                "feature_list_hash": feature_contract_hash(feature_names),
                "base_score": 0.0,
                "trees": [
                    {
                        "shrinkage": 1.0,
                        "tree_structure": {"leaf_value": 0.25},
                    }
                ],
                "metadata": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_validate_artifact_preflights_default_model_artifact(tmp_path: Path, monkeypatch) -> None:
    artifact_path = tmp_path / "bct_lambdamart_qc_safe_v1.json"
    _write_artifact(artifact_path, feature_names=("gap_pct",))
    monkeypatch.setattr(M, "DEFAULT_ARTIFACT_PATH", artifact_path)
    variants = [variant for variant in first_pack() if variant.variant_id == "scanner_lambdamart_top10"]

    artifact, artifact_hash = M._validate_artifact(
        SimpleNamespace(artifact=artifact_path, allow_missing_artifact=False),
        variants,
    )

    assert artifact == artifact_path.resolve()
    assert artifact_hash


def test_validate_artifact_rejects_denied_runtime_feature(tmp_path: Path, monkeypatch) -> None:
    artifact_path = tmp_path / "bct_lambdamart_qc_safe_v1.json"
    _write_artifact(artifact_path, feature_names=("george_label",))
    monkeypatch.setattr(M, "DEFAULT_ARTIFACT_PATH", artifact_path)
    variants = [variant for variant in first_pack() if variant.variant_id == "scanner_lambdamart_top10"]

    with pytest.raises(SystemExit, match="artifact invalid.*denied"):
        M._validate_artifact(
            SimpleNamespace(artifact=artifact_path, allow_missing_artifact=False),
            variants,
        )


def test_data_fingerprint_uses_requested_data_folder(tmp_path: Path) -> None:
    data_folder = tmp_path / "market-data"
    data_folder.mkdir()
    (data_folder / "MANIFEST.json").write_text(
        json.dumps({"fingerprint": "requested-data-fp"}) + "\n",
        encoding="utf-8",
    )

    assert M._data_fingerprint(data_folder) == "requested-data-fp"


def test_dist_builder_injects_window_cache_and_data_folder(tmp_path: Path, monkeypatch) -> None:
    def fake_build_sweep_dist(config, dist_dir, base_module) -> None:  # type: ignore[no-untyped-def]
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "main.py").write_text(
            "class BCTAlgorithm:\n"
            "    STRATEGY_CONFIG = STRATEGY_CONFIG\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(M, "build_sweep_dist", fake_build_sweep_dist)
    monkeypatch.setattr(M, "_link_repo_storage", lambda run_dir: None)
    data_folder = tmp_path / "data"
    data_folder.mkdir()
    run_dir = tmp_path / "run"
    window = M.WINDOWS["jan"]
    config = first_pack()[0].config

    marker = M._dist_builder(window, "fp-123", data_folder)(config, window, run_dir)

    main = (run_dir / "main.py").read_text(encoding="utf-8")
    lean_config = json.loads((run_dir / "lean.json").read_text(encoding="utf-8"))
    assert marker in main
    assert "START_DATE = (2025, 1, 13)" in main
    assert "END_DATE = (2025, 1, 31)" in main
    assert "BCTAlgorithm.WARMUP_WEEKLY_CACHE_FP = 'fp-123'" in main
    assert lean_config["data-folder"] == str(data_folder.resolve())


def test_dist_builder_fails_when_window_injection_anchor_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_build_sweep_dist(config, dist_dir, base_module) -> None:  # type: ignore[no-untyped-def]
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "main.py").write_text("class BCTAlgorithm:\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(M, "build_sweep_dist", fake_build_sweep_dist)
    window = M.WINDOWS["jan"]
    config = first_pack()[0].config

    with pytest.raises(RuntimeError, match="window injection anchor missing"):
        M._dist_builder(window, "", tmp_path / "data")(config, window, tmp_path / "run")


def test_repo_ref_relativizes_repo_paths() -> None:
    path = M.ROOT / "sweeps" / "reports" / "example" / "summary.csv"

    assert M._repo_ref(path) == "sweeps/reports/example/summary.csv"


def test_raise_on_failures_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        M._raise_on_failures(
            [
                {"variant_id": "ok", "ok": True, "error": ""},
                {"variant_id": "bad", "ok": False, "error": "boom"},
            ]
        )

    assert exc_info.value.code == 1
