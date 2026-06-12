from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts import train_intraday_entry_exit_policy as M


def test_validate_feature_names_blocks_oracle_and_label_leakage() -> None:
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "oracle_best_entry_price"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "entry_action_label"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "best_deployable_total_equity_ret_40d_pct"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "triggered_entry_assumptions"])
    with pytest.raises(ValueError):
        M.validate_feature_names(["kumo_score", "next_open_entry_gap_pct"])


def test_softmax_linear_fits_simple_separable_data() -> None:
    x = np.array([[-2.0], [-1.0], [1.0], [2.0]], dtype=float)
    y = np.array([0, 0, 1, 1], dtype=int)

    model = M.fit_softmax_linear(x, y, ("left", "right"), max_iter=120, learning_rate=0.1, l2=0.0)
    probs = M.predict_proba(model, x)

    assert probs[:2, 0].mean() > 0.5
    assert probs[2:, 1].mean() > 0.5


def test_add_policy_features_excludes_label_columns_and_adds_categories() -> None:
    frame = pd.DataFrame(
        [
            {
                "scan_date": "2025-01-01",
                "symbol": "AAA",
                "row_type": "entry_decision",
                "checkpoint": "first_hour",
                "scanner_source_bucket": "kumo_only",
                "sector_category": "Tech",
                "entry_action_label": "enter_now",
                "management_action_label": "",
                "prior_model_combined_score": 0.75,
                "kumo_signal_seen": True,
                "kumo_top_n": True,
                "kumo_scanner": True,
                "george_signal_seen": False,
                "george_scanner_positive": False,
                "george_watchlist": False,
                "george_video_mention": False,
                "intraday_available": True,
                "last_15m_available": True,
                "last_hour_available": True,
                "etf_intraday_available": False,
                "etf_last_15m_available": False,
                "etf_last_hour_available": False,
                "ichimoku_15m_available": False,
                "ichimoku_hour_available": False,
                "etf_ichimoku_15m_available": False,
                "etf_ichimoku_hour_available": False,
                "volume_so_far": 1000,
                "last_15m_volume": 500,
                "last_hour_volume": 1000,
                "etf_volume_so_far": 0,
                "etf_last_15m_volume": 0,
                "etf_last_hour_volume": 0,
                "oracle_best_entry_price": 123.0,
                "triggered_entry_assumptions": 4,
                "next_open_entry_gap_pct": 2.5,
            }
        ]
    )

    out, features = M.add_policy_features(frame)

    assert "checkpoint_first_hour" in features
    assert "source_bucket_kumo_only" in features
    assert "sector_tech" in features
    assert "entry_action_label" not in features
    assert "oracle_best_entry_price" not in features
    assert "triggered_entry_assumptions" not in features
    assert "next_open_entry_gap_pct" not in features
    assert "prior_model_combined_score" not in features
    assert "is_ichimoku_15m_available" in features
    assert out.loc[0, "volume_so_far_log"] > 0


def test_baseline_entry_action_uses_only_asof_state() -> None:
    frame = pd.DataFrame(
        [
            {"return_from_open_pct": -2.0, "mae_from_open_pct": -2.5, "distance_from_vwap_pct": -1.0, "kumo_score": 8, "checkpoint": "first_hour"},
            {"return_from_open_pct": 1.0, "mae_from_open_pct": 0.0, "distance_from_vwap_pct": 0.2, "kumo_score": 8, "checkpoint": "first_hour"},
            {"return_from_open_pct": 0.0, "mae_from_open_pct": 0.0, "distance_from_vwap_pct": 0.0, "kumo_score": 6, "checkpoint": "open"},
        ]
    )

    assert M.baseline_entry_action(frame).tolist() == ["avoid_bad_entry", "enter_now", "wait"]


def test_action_metrics_computes_precision_recall() -> None:
    predictions = pd.DataFrame(
        [
            {"policy_name": "entry_policy", "oof_available_490": True, "label_action": "enter_now", "predicted_action": "enter_now", "baseline_action": "wait"},
            {"policy_name": "entry_policy", "oof_available_490": True, "label_action": "wait", "predicted_action": "enter_now", "baseline_action": "wait"},
            {"policy_name": "entry_policy", "oof_available_490": True, "label_action": "wait", "predicted_action": "wait", "baseline_action": "wait"},
        ]
    )

    metrics = M.action_metrics(predictions, pred_col="predicted_action").set_index("action")

    assert metrics.loc["enter_now", "precision_pct"] == 50.0
    assert metrics.loc["enter_now", "recall_pct"] == 100.0


def test_walk_forward_splits_train_before_validation() -> None:
    splits = M.make_walk_forward_splits(
        ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"],
        n_folds=4,
        min_train_folds=1,
    )

    assert len(splits) == 3
    assert all(max(split["train_dates"]) < min(split["valid_dates"]) for split in splits)
