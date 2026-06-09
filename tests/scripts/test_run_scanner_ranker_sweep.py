from __future__ import annotations

from types import SimpleNamespace

import pytest

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
