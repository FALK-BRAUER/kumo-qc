"""Tests for the George-label coverage-stage audit helper."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from sweeps.archive import candidates as C
from sweeps.archive import george_coverage_audit as A


def _universe() -> dict[str, list[str]]:
    return {"2026-02-12": ["AAA", "BBB", "LOW", "THIN", "COLD", "PARA"]}


def _metrics() -> dict[str, dict[str, tuple[float, float, float]]]:
    return {
        "2026-02-12": {
            "aaa": (50.0, 200_000_000.0, 200_000_000.0),
            "bbb": (50.0, 200_000_000.0, 200_000_000.0),
            "low": (5.0, 200_000_000.0, 200_000_000.0),
            "thin": (50.0, 10_000_000.0, 200_000_000.0),
            "cold": (50.0, 200_000_000.0, 50_000_000.0),
            "para": (50.0, 200_000_000.0, 200_000_000.0),
        }
    }


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0], "volume": [1.0]},
        index=[pd.Timestamp("2026-02-12")],
    )


def _patch_common(monkeypatch, *, feats: dict[str, float] | None = None, score: int | None = 8) -> None:
    monkeypatch.setattr(A, "load_daily_frame", lambda _symbol, _daily_dir: _frame())
    if feats is None:
        feats = {"close": 50.0, "sma200": 40.0, "daily_cloud_top": 45.0, "roc13": 0.05}
    monkeypatch.setattr(A, "_features_from_daily", lambda _daily: feats)
    if score is None:
        monkeypatch.setattr(A, "score_from_daily_frame", lambda _daily: None)
    else:
        monkeypatch.setattr(
            A,
            "score_from_daily_frame",
            lambda _daily: {"score": score, "rating": "+++", "conditions": [True] * score + [False] * (8 - score)},
        )


def test_stage_not_in_coarse_feed() -> None:
    row = A.audit_label("2026-02-12", "MISS", universe=_universe(), coarse_metrics=_metrics())
    assert row.stage == A.STAGE_NOT_IN_COARSE_FEED


def test_stage_floor_failures() -> None:
    low = A.audit_label("2026-02-12", "LOW", universe=_universe(), coarse_metrics=_metrics())
    thin = A.audit_label("2026-02-12", "THIN", universe=_universe(), coarse_metrics=_metrics())
    cold = A.audit_label("2026-02-12", "COLD", universe=_universe(), coarse_metrics=_metrics())
    assert low.stage == A.STAGE_FAILS_PRICE_FLOOR
    assert thin.stage == A.STAGE_FAILS_PREFILTER_DV
    assert cold.stage == A.STAGE_FAILS_TRAILING_DV_FLOOR


def test_stage_bct_prefilter_failure(monkeypatch) -> None:
    _patch_common(monkeypatch, feats={"close": 39.0, "sma200": 40.0, "daily_cloud_top": 38.0, "roc13": 0.05})
    row = A.audit_label("2026-02-12", "AAA", universe=_universe(), coarse_metrics=_metrics())
    assert row.stage == A.STAGE_FAILS_BCT_PREFILTER
    assert row.passed_bct_prefilter is False


def test_stage_score_below_min(monkeypatch) -> None:
    _patch_common(monkeypatch, score=6)
    row = A.audit_label("2026-02-12", "AAA", universe=_universe(), coarse_metrics=_metrics())
    assert row.stage == A.STAGE_BCT_SCORE_BELOW_MIN
    assert row.score == 6


def test_stage_parabolic_block(monkeypatch) -> None:
    _patch_common(monkeypatch, feats={"close": 50.0, "sma200": 40.0, "daily_cloud_top": 45.0, "roc13": 0.30})
    row = A.audit_label("2026-02-12", "PARA", universe=_universe(), coarse_metrics=_metrics())
    assert row.stage == A.STAGE_PARABOLIC_BLOCK
    assert row.passed_score is True
    assert row.passed_parabolic is False


def test_stage_qc_candidate_carries_rank_fields(monkeypatch) -> None:
    _patch_common(monkeypatch)
    candidate = C.CandidateRow(
        date="2026-02-12",
        symbol="AAA",
        score=8,
        rating="+++",
        conditions=[True] * 8,
        close=50.0,
        daily_tenkan=49.0,
        daily_kijun=45.0,
        sma200=40.0,
        daily_cloud_a=44.0,
        daily_cloud_b=43.0,
        daily_cloud_top=44.0,
        weekly_cloud_a=42.0,
        weekly_cloud_b=41.0,
        weekly_cloud_top=42.0,
        weekly_tenkan=43.0,
        weekly_kijun=42.0,
        adx=25.0,
        plus_di=30.0,
        minus_di=10.0,
        roc13=0.05,
        single_day_dv=200_000_000.0,
        trailing_dv=200_000_000.0,
        scanner_rank=1,
        passed_prefilter=True,
        passed_floors=True,
        passed_parabolic=True,
        bct_signal_rank=4,
        george_style_rank=2,
        george_style_score=12.5,
        george_constructive_resistance=True,
        george_bad_resistance=False,
        george_no_chase_risk=False,
    )
    row = A.audit_label(
        "2026-02-12",
        "AAA",
        universe=_universe(),
        coarse_metrics=_metrics(),
        candidate_row_by_key={("2026-02-12", "AAA"): candidate},
    )
    assert row.stage == A.STAGE_QC_CANDIDATE
    assert row.bct_signal_rank == 4
    assert row.george_style_rank == 2
    assert row.george_style_score == 12.5
    assert row.george_constructive_resistance is True


def test_load_labels_and_summary(tmp_path: Path) -> None:
    labels = tmp_path / "labels.csv"
    labels.write_text(
        "date,symbol,george_included\n"
        "2026-02-12,AAA,True\n"
        "2026-02-12,BBB,False\n"
        "2026-02-13,AAA,True\n"
    )
    assert A.load_george_labels(labels) == [("2026-02-12", "AAA"), ("2026-02-13", "AAA")]
    rows = [
        A.GeorgeCoverageAuditRow("2026-02-12", "AAA", A.STAGE_QC_CANDIDATE),
        A.GeorgeCoverageAuditRow("2026-02-13", "AAA", A.STAGE_NOT_IN_COARSE_FEED),
    ]
    summary = A.summarize_audit(rows)
    assert summary.set_index("stage").loc[A.STAGE_QC_CANDIDATE, "rows"] == 1
    assert summary.set_index("stage").loc[A.STAGE_NOT_IN_COARSE_FEED, "pct"] == 50.0
