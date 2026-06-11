from __future__ import annotations

import pandas as pd
import pytest

from scripts import train_scanner_opportunity_ranker as M


def test_validate_feature_names_blocks_source_and_future_leakage() -> None:
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "george_watchlist"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "label_ret_20d_close_pct"])


def test_walk_forward_splits_train_before_validation() -> None:
    splits = M.make_walk_forward_splits(
        ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"],
        n_folds=4,
        min_train_folds=1,
    )

    assert len(splits) == 3
    for split in splits:
        assert max(split["train_dates"]) < min(split["valid_dates"])


def test_topk_metrics_compute_recall_precision_and_ndcg() -> None:
    frame = pd.DataFrame(
        [
            {
                "scan_date": "2025-01-01",
                "score": 3.0,
                "target_trade_worthy": True,
                "label_ret_20d_close_pct": 10.0,
                "label_mfe_20d_pct": 15.0,
                "label_bad_trade_20d": False,
            },
            {
                "scan_date": "2025-01-01",
                "score": 2.0,
                "target_trade_worthy": False,
                "label_ret_20d_close_pct": -5.0,
                "label_mfe_20d_pct": 2.0,
                "label_bad_trade_20d": True,
            },
            {
                "scan_date": "2025-01-01",
                "score": 1.0,
                "target_trade_worthy": True,
                "label_ret_20d_close_pct": 8.0,
                "label_mfe_20d_pct": 10.0,
                "label_bad_trade_20d": False,
            },
        ]
    )

    metrics = M.topk_metrics(frame, target_col="target_trade_worthy", score_col="score", ks=(2,))
    row = metrics.iloc[0]

    assert row["selected_rows"] == 2
    assert row["positive_rows"] == 2
    assert row["hit_rows"] == 1
    assert row["recall_pct"] == 50.0
    assert row["precision_pct"] == 50.0
    assert row["bad_trade_pct_topk"] == 50.0


def test_add_scan_time_features_excludes_george_source_flags_from_feature_list() -> None:
    frame = pd.DataFrame(
        [
            {
                "scan_date": "2025-01-01",
                "symbol": "AAA",
                "kumo_rank_by_score": 1,
                "kumo_score": 8,
                "kumo_gap_pct": 2.0,
                "kumo_vol_ratio_20d": 1.5,
                "kumo_dollar_vol": 1_000_000,
                "kumo_volume": 100_000,
                "kumo_close": 10,
                "kumo_top_n": True,
                "kumo_scanner": True,
                "sector_etf_proxy": "XLK",
                "george_scanner_positive": True,
            }
        ]
    )

    _panel, features = M.add_scan_time_features(frame)

    assert features
    assert all("george" not in feature for feature in features)
    assert all("label" not in feature for feature in features)
