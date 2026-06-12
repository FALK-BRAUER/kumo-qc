from __future__ import annotations

import pandas as pd
import pytest

from scripts import train_scan_time_scanner_ranker as M


def test_validate_feature_names_blocks_source_and_outcome_leakage() -> None:
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "george_scanner_positive"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "best_entry_ret_20d_close_pct"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "best_deployable_exit_status"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "target_optimal"])


def test_prepare_labels_maps_optimal_bad_watch_buckets() -> None:
    frame = pd.DataFrame(
        {
            "trade_bucket": ["optimal", "bad", "watch"],
            "scan_date": ["2025-01-01"] * 3,
            "symbol": ["AAA", "BBB", "CCC"],
        }
    )

    out = M.prepare_labels(frame)

    assert out["target_optimal"].tolist() == [True, False, False]
    assert out["target_bad_risk"].tolist() == [False, True, False]
    assert out["target_watch"].tolist() == [False, False, True]
    assert out["target_relevance"].tolist() == [2.0, 0.0, 0.5]


def test_add_scan_time_features_uses_only_allowed_feature_names() -> None:
    frame = pd.DataFrame(
        [
            {
                "scan_date": "2025-01-01",
                "symbol": "AAA",
                "trade_bucket": "optimal",
                "kumo_rank_by_score": 1,
                "kumo_score": 8,
                "kumo_gap_pct": 2.0,
                "kumo_vol_ratio_20d": 1.5,
                "kumo_dollar_vol": 1_000_000,
                "kumo_volume": 100_000,
                "kumo_close": 10,
                "kumo_top_n": True,
                "company_sector": "Technology",
                "company_industry": "Software",
                "sector_category": "Technology",
                "sector_etf_proxy": "XLK",
                "george_scanner_positive": True,
                "best_entry_ret_20d_close_pct": 100.0,
            },
            {
                "scan_date": "2025-01-01",
                "symbol": "BBB",
                "trade_bucket": "bad",
                "kumo_rank_by_score": 2,
                "kumo_score": 7,
                "kumo_gap_pct": -3.0,
                "kumo_vol_ratio_20d": 0.8,
                "kumo_dollar_vol": 2_000_000,
                "kumo_volume": 150_000,
                "kumo_close": 20,
                "kumo_top_n": True,
                "company_sector": "",
                "company_industry": "",
                "sector_category": "Healthcare",
                "sector_etf_proxy": "XLV",
                "george_scanner_positive": False,
                "best_entry_ret_20d_close_pct": -20.0,
            },
        ]
    )

    out, features = M.add_scan_time_features(M.prepare_labels(frame))

    assert "score_x_rank_pct" in features
    assert "sector_cat_technology" in features
    assert all("george" not in feature for feature in features)
    assert all("entry" not in feature for feature in features)
    assert out.loc[0, "sector_cat_technology"] == 1.0
    assert out.loc[1, "sector_cat_healthcare"] == 1.0


def test_walk_forward_splits_train_before_validation() -> None:
    splits = M.make_walk_forward_splits(
        ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"],
        n_folds=4,
        min_train_folds=1,
    )

    assert len(splits) == 3
    for split in splits:
        assert max(split["train_dates"]) < min(split["valid_dates"])


def test_topk_metrics_compute_optimal_precision_bad_rate_and_ndcg() -> None:
    frame = pd.DataFrame(
        [
            {
                "scan_date": "2025-01-01",
                "score": 3.0,
                "target_optimal": True,
                "target_bad_risk": False,
                "target_watch": False,
                "target_relevance": 2.0,
                "best_entry_ret_20d_close_pct": 10.0,
                "best_entry_mfe_20d_pct": 15.0,
                "best_entry_mae_20d_pct": -2.0,
                "best_deployable_total_equity_ret_40d_pct": 8.0,
            },
            {
                "scan_date": "2025-01-01",
                "score": 2.0,
                "target_optimal": False,
                "target_bad_risk": True,
                "target_watch": False,
                "target_relevance": 0.0,
                "best_entry_ret_20d_close_pct": -5.0,
                "best_entry_mfe_20d_pct": 2.0,
                "best_entry_mae_20d_pct": -8.0,
                "best_deployable_total_equity_ret_40d_pct": -2.0,
            },
            {
                "scan_date": "2025-01-01",
                "score": 1.0,
                "target_optimal": True,
                "target_bad_risk": False,
                "target_watch": False,
                "target_relevance": 2.0,
                "best_entry_ret_20d_close_pct": 8.0,
                "best_entry_mfe_20d_pct": 10.0,
                "best_entry_mae_20d_pct": -3.0,
                "best_deployable_total_equity_ret_40d_pct": 6.0,
            },
        ]
    )

    metrics = M.topk_metrics(frame, score_col="score", ks=(2,))
    row = metrics.iloc[0]

    assert row["selected_rows"] == 2
    assert row["optimal_rows"] == 2
    assert row["optimal_hits"] == 1
    assert row["optimal_recall_pct"] == 50.0
    assert row["optimal_precision_pct"] == 50.0
    assert row["bad_trade_pct_topk"] == 50.0
    assert row["ndcg_mean"] > 0


def test_daily_examples_finds_promoted_optimal_and_demoted_bad() -> None:
    frame = pd.DataFrame(
        [
            {
                "scan_date": "2025-01-01",
                "symbol": "BAD",
                "trade_bucket": "bad",
                "target_optimal": False,
                "target_bad_risk": True,
                "oof_available_492": True,
                "baseline_492_kumo_rank_score": -1.0,
                "model_492_optimal_score": 1.0,
                "model_492_combined_score": 1.0,
                "kumo_rank_by_score": 1,
                "kumo_score": 8,
            },
            {
                "scan_date": "2025-01-01",
                "symbol": "OPT",
                "trade_bucket": "optimal",
                "target_optimal": True,
                "target_bad_risk": False,
                "oof_available_492": True,
                "baseline_492_kumo_rank_score": -3.0,
                "model_492_optimal_score": 3.0,
                "model_492_combined_score": 3.0,
                "kumo_rank_by_score": 3,
                "kumo_score": 8,
            },
            {
                "scan_date": "2025-01-01",
                "symbol": "MID",
                "trade_bucket": "watch",
                "target_optimal": False,
                "target_bad_risk": False,
                "oof_available_492": True,
                "baseline_492_kumo_rank_score": -2.0,
                "model_492_optimal_score": 2.0,
                "model_492_combined_score": 2.0,
                "kumo_rank_by_score": 2,
                "kumo_score": 7,
            },
        ]
    )

    for column in [
        "model_492_bad_risk_score",
        "prior_467_combined_score",
        "best_entry_ret_20d_close_pct",
        "best_entry_mfe_20d_pct",
        "best_entry_mae_20d_pct",
        "best_deployable_total_equity_ret_40d_pct",
        "reason_codes",
        "company_sector",
        "company_industry",
        "sector_category",
        "sector_etf_proxy",
    ]:
        frame[column] = None

    examples = M.daily_examples(frame, k=1)

    assert set(examples["example_type"]) == {"optimal_model_promoted_optimal", "risk_blend_demoted_bad"}
