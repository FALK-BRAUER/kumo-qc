from __future__ import annotations

import pandas as pd

from scripts import analyze_scanner_entry_triggers as M


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scan_date": "2025-01-01",
                "symbol": "AAA",
                "source_tags": "kumo_scanner;kumo_top_n",
                "kumo_scanner": True,
                "kumo_top_n": True,
                "george_scanner_positive": False,
                "george_watchlist": False,
                "george_video_mention": False,
                "kumo_rank_by_score": 10,
                "kumo_score": 8,
                "george_rank": None,
                "george_watchlist_rank": None,
                "label_entry_gap_pct": 2.0,
                "label_ret_20d_close_pct": 12.0,
                "label_mfe_20d_pct": 18.0,
                "label_mae_20d_pct": -2.0,
                "label_t4_s2_20d_outcome": "target_before_stop",
                "label_t8_s4_20d_outcome": "target_before_stop",
                "label_runner_candidate_20d": True,
                "label_normal_winner_20d": True,
                "label_bad_trade_20d": False,
                "label_extreme_path_flag": False,
                "label_outcome_20d": "runner_candidate",
            },
            {
                "scan_date": "2025-01-01",
                "symbol": "BBB",
                "source_tags": "kumo_scanner",
                "kumo_scanner": True,
                "kumo_top_n": False,
                "george_scanner_positive": False,
                "george_watchlist": False,
                "george_video_mention": False,
                "kumo_rank_by_score": 200,
                "kumo_score": 6,
                "george_rank": None,
                "george_watchlist_rank": None,
                "label_entry_gap_pct": 9.0,
                "label_ret_20d_close_pct": -5.0,
                "label_mfe_20d_pct": 3.0,
                "label_mae_20d_pct": -8.0,
                "label_t4_s2_20d_outcome": "stop_before_target",
                "label_t8_s4_20d_outcome": "stop_before_target",
                "label_runner_candidate_20d": False,
                "label_normal_winner_20d": False,
                "label_bad_trade_20d": True,
                "label_extreme_path_flag": False,
                "label_outcome_20d": "bad_trade",
            },
        ]
    )


def test_gate_summary_scores_top_rank_gate() -> None:
    frame = _frame()
    frame["entry_good_20d"] = (
        (frame["label_runner_candidate_20d"] | frame["label_normal_winner_20d"])
        & ~frame["label_bad_trade_20d"]
    )
    frame["entry_available_20d"] = frame["label_ret_20d_close_pct"].notna()
    frame["george_scanner_or_watchlist"] = frame["george_scanner_positive"] | frame["george_watchlist"]

    summary = M.gate_summary(frame).set_index("gate_id")

    assert summary.loc["kumo_top20", "available_rows"] == 1
    assert summary.loc["kumo_top20", "avg_ret_20d_close_pct"] == 12.0
    assert summary.loc["kumo_top20", "bad_trade_pct"] == 0.0
    assert summary.loc["next_open_all", "bad_trade_pct"] == 50.0


def test_bucket_summary_splits_rank_and_gap() -> None:
    frame = _frame()
    frame["entry_good_20d"] = (
        (frame["label_runner_candidate_20d"] | frame["label_normal_winner_20d"])
        & ~frame["label_bad_trade_20d"]
    )
    frame["entry_available_20d"] = frame["label_ret_20d_close_pct"].notna()

    buckets = M.bucket_summary(frame).set_index("bucket")

    assert buckets.loc["rank_1_10", "rows"] == 1
    assert buckets.loc["rank_101_250", "rows"] == 1
    assert buckets.loc["gap_2_to_5", "avg_ret_20d_close_pct"] == 12.0
    assert buckets.loc["gap_gt_8", "bad_trade_pct"] == 100.0
