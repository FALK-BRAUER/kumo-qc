from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.scanner_ranker import ARTIFACT_SCHEMA_VERSION, feature_contract_hash, opportunity_feature_contract_hash
from scripts import run_scanner_ranker_sweep as M
from sweeps.grids.scanner_ranker import (
    DEFAULT_OPPORTUNITY_MODEL_KEY,
    first_pack,
    opportunity_ranker_pack,
    rank_aware_intraday_pack,
    real_strategy_scanner_pack,
    top20_realized_exit_pack,
    top_x_expansion_pack,
)


def test_variants_filters_named_subset_in_pack_order() -> None:
    args = SimpleNamespace(
        pack="first",
        only="scanner_lambdamart_top20,scanner_champion_baseline",
        limit=None,
    )

    variants = M._variants(args)

    assert [variant.variant_id for variant in variants] == [
        "scanner_champion_baseline",
        "scanner_lambdamart_top20",
    ]


def test_variants_rejects_unknown_id() -> None:
    args = SimpleNamespace(pack="first", only="missing_variant", limit=None)

    with pytest.raises(SystemExit, match="missing_variant"):
        M._variants(args)


def test_variants_selects_top_x_expansion_pack() -> None:
    args = SimpleNamespace(pack="top_x_expansion", only="", limit=None)

    variants = M._variants(args)

    assert [variant.variant_id for variant in variants] == [
        variant.variant_id for variant in top_x_expansion_pack()
    ]


def test_variants_selects_real_strategy_scanner_pack() -> None:
    args = SimpleNamespace(pack="real_strategy_scanner", only="", limit=None)

    variants = M._variants(args)

    assert [variant.variant_id for variant in variants] == [
        variant.variant_id for variant in real_strategy_scanner_pack()
    ]


def test_variants_selects_top20_realized_exit_pack() -> None:
    args = SimpleNamespace(pack="top20_realized_exit", only="", limit=None)

    variants = M._variants(args)

    assert [variant.variant_id for variant in variants] == [
        variant.variant_id for variant in top20_realized_exit_pack()
    ]


def test_variants_selects_rank_aware_intraday_pack() -> None:
    args = SimpleNamespace(pack="rank_aware_intraday", only="", limit=None)

    variants = M._variants(args)

    assert [variant.variant_id for variant in variants] == [
        variant.variant_id for variant in rank_aware_intraday_pack()
    ]


def test_variants_selects_opportunity_ranker_pack() -> None:
    args = SimpleNamespace(pack="opportunity_ranker", only="", limit=None)

    variants = M._variants(args)

    assert [variant.variant_id for variant in variants] == [
        variant.variant_id for variant in opportunity_ranker_pack()
    ]


def _artifact_args(tmp_path: Path, *, artifact: Path | None = None, opportunity_artifact: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        artifact=artifact or tmp_path / "missing.json",
        opportunity_artifact=opportunity_artifact or tmp_path / "missing-opportunity.json",
        allow_missing_artifact=False,
    )


def test_default_artifact_required_only_for_default_model_variants(tmp_path: Path) -> None:
    default_variants = [
        variant for variant in first_pack() if variant.variant_id == "scanner_lambdamart_top10"
    ]
    fallback_variants = [
        variant for variant in first_pack() if variant.variant_id == "scanner_ranker_fallback_bct_order"
    ]

    with pytest.raises(SystemExit, match="artifact missing"):
        M._validate_artifacts(_artifact_args(tmp_path), default_variants)

    assert M._validate_artifacts(_artifact_args(tmp_path), fallback_variants) == {}


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


def _write_linear_artifact(path: Path, *, feature_names: tuple[str, ...] = ("kumo_score",)) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "model_type": "linear_pairwise_ranker",
                "feature_version": "scanner_opportunity_scan_time_v1",
                "feature_hash": opportunity_feature_contract_hash(feature_names),
                "feature_names": list(feature_names),
                "standardizer": {"mean": [0.0 for _ in feature_names], "scale": [1.0 for _ in feature_names]},
                "models": {
                    "trade_worthy": {"coef": [1.0 for _ in feature_names], "intercept": 0.0},
                    "runner": {"coef": [1.0 for _ in feature_names], "intercept": 0.0},
                },
                "combined_score": {"trade_worthy_weight": 0.7, "runner_weight": 0.3},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_validate_artifact_preflights_default_model_artifact(tmp_path: Path, monkeypatch) -> None:
    artifact_path = tmp_path / "bct_lambdamart_qc_safe_v1.json"
    _write_artifact(artifact_path, feature_names=("gap_pct",))
    monkeypatch.setattr(M, "ROOT", tmp_path)
    variants = [variant for variant in first_pack() if variant.variant_id == "scanner_lambdamart_top10"]

    bindings = M._validate_artifacts(_artifact_args(tmp_path, artifact=artifact_path), variants)
    binding = bindings["scanner_lambdamart_top10"]

    assert Path(binding["artifact_path"]) == artifact_path.resolve()
    assert binding["artifact_sha256"]
    assert Path(binding["staged_path"]) == tmp_path / "storage" / "bct_lambdamart_qc_safe_v1.json"


def test_validate_artifact_stages_opportunity_model_artifact(tmp_path: Path, monkeypatch) -> None:
    artifact_path = tmp_path / "scanner_opportunity_ranker_467_v1.json"
    _write_linear_artifact(artifact_path)
    monkeypatch.setattr(M, "ROOT", tmp_path)
    variant = next(item for item in opportunity_ranker_pack() if item.variant_id == "opportunity_linear_top20")
    variant = replace(variant, local_artifact_path=str(artifact_path))

    bindings = M._validate_artifacts(_artifact_args(tmp_path), [variant])
    binding = bindings["opportunity_linear_top20"]

    assert binding["model_path"] == DEFAULT_OPPORTUNITY_MODEL_KEY
    assert Path(binding["artifact_path"]) == artifact_path.resolve()
    assert Path(binding["staged_path"]) == tmp_path / "storage" / "scanner_opportunity_ranker_467_v1.json"


def test_validate_artifact_rejects_denied_runtime_feature(tmp_path: Path, monkeypatch) -> None:
    artifact_path = tmp_path / "bct_lambdamart_qc_safe_v1.json"
    _write_artifact(artifact_path, feature_names=("george_label",))
    monkeypatch.setattr(M, "ROOT", tmp_path)
    variants = [variant for variant in first_pack() if variant.variant_id == "scanner_lambdamart_top10"]

    with pytest.raises(SystemExit, match="artifact invalid.*denied"):
        M._validate_artifacts(_artifact_args(tmp_path, artifact=artifact_path), variants)


def test_data_fingerprint_uses_requested_data_folder(tmp_path: Path) -> None:
    data_folder = tmp_path / "market-data"
    data_folder.mkdir()
    (data_folder / "MANIFEST.json").write_text(
        json.dumps({"fingerprint": "requested-data-fp"}) + "\n",
        encoding="utf-8",
    )

    assert M._data_fingerprint(data_folder) == "requested-data-fp"


def test_dist_builder_injects_window_cache_and_data_folder(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_build_sweep_dist(config, dist_dir, base_module) -> None:  # type: ignore[no-untyped-def]
        calls.append(base_module)
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

    marker = M._dist_builder(
        window,
        "fp-123",
        data_folder,
        "strategies.realized_giveback_no_bull",
    )(config, window, run_dir)

    main = (run_dir / "main.py").read_text(encoding="utf-8")
    lean_config = json.loads((run_dir / "lean.json").read_text(encoding="utf-8"))
    assert calls == ["strategies.realized_giveback_no_bull"]
    assert marker in main
    assert "strategies.realized_giveback_no_bull" in marker
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


def test_needs_variant_run_roots_for_multi_base_duplicate_hash_pack() -> None:
    assert M._needs_variant_run_roots(real_strategy_scanner_pack()) is True
    assert M._needs_variant_run_roots(first_pack()) is False


def test_variant_runs_root_isolates_by_variant_id(tmp_path: Path) -> None:
    variant = real_strategy_scanner_pack()[0]

    root = M._variant_runs_root(tmp_path, variant, isolate_run_dirs=True)

    assert root == tmp_path / variant.variant_id
    assert (root / "README.md").exists()


def test_variant_runs_root_can_reuse_pack_root(tmp_path: Path) -> None:
    variant = first_pack()[0]

    root = M._variant_runs_root(tmp_path, variant, isolate_run_dirs=False)

    assert root == tmp_path


def test_result_diagnostics_parses_lean_trade_and_runtime_stats(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "runtimeStatistics": {"Unrealized": "$1,234.56"},
                "totalPerformance": {
                    "tradeStatistics": {
                        "totalNumberOfTrades": 12,
                        "numberOfWinningTrades": 9,
                        "numberOfLosingTrades": 3,
                        "totalProfitLoss": "$2,500.00",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    diagnostics = M._result_diagnostics(result_path)

    assert diagnostics == {
        "realized_net": "$2,500.00",
        "unrealized": "$1,234.56",
        "closed_trades": 12,
        "closed_wins": 9,
        "closed_losses": 3,
        "closed_win_rate": 75.0,
    }


def test_result_diagnostics_falls_back_to_archive_closed_trade_count(tmp_path: Path) -> None:
    result_path = tmp_path / "archive-result.json"
    result_path.write_text(json.dumps({"n_closed_trades": 7}) + "\n", encoding="utf-8")

    diagnostics = M._result_diagnostics(result_path)

    assert diagnostics["closed_trades"] == 7
    assert diagnostics["closed_win_rate"] == ""


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
