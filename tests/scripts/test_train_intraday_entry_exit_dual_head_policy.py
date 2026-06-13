from __future__ import annotations

import numpy as np
import pandas as pd

from scripts import train_intraday_entry_exit_dual_head_policy as M


def _entry_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "scan_date": "2025-01-01",
        "symbol": "AAA",
        "opportunity_id": "2025-01-01|AAA",
        "row_type": "entry_decision",
        "checkpoint": "first_hour",
        "scanner_source_bucket": "kumo_only",
        "trade_bucket": "watch",
        "oracle_best_entry_outcome_20d": "no_realistic_entry",
        "entry_action_label": "wait",
        "management_action_label": "",
    }
    row.update(overrides)
    return row


def _management_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "scan_date": "2025-01-01",
        "symbol": "AAA",
        "opportunity_id": "2025-01-01|AAA",
        "row_type": "position_management",
        "checkpoint": "first_hour",
        "scanner_source_bucket": "kumo_only",
        "trade_bucket": "optimal",
        "oracle_best_entry_outcome_20d": "runner_candidate",
        "entry_action_label": "",
        "management_action_label": "hold_or_wait",
    }
    row.update(overrides)
    return row


def test_entry_targets_separate_bad_risk_from_winner_preservation() -> None:
    frame = pd.DataFrame(
        [
            _entry_row(trade_bucket="bad", entry_action_label="avoid_bad_entry"),
            _entry_row(trade_bucket="optimal", oracle_best_entry_outcome_20d="runner_candidate", entry_action_label="enter_now"),
            _entry_row(trade_bucket="watch", entry_action_label="wait"),
        ]
    )

    assert M.entry_bad_risk_target(frame).tolist() == [True, False, False]
    assert M.entry_winner_preservation_target(frame).tolist() == [False, True, False]
    assert M.entry_ready_target(frame).tolist() == [False, True, False]


def test_management_targets_separate_exit_risk_from_runner_preservation() -> None:
    frame = pd.DataFrame(
        [
            _management_row(management_action_label="exit_loser"),
            _management_row(management_action_label="do_not_cut_runner"),
            _management_row(management_action_label="hold_or_wait"),
        ]
    )

    assert M.management_exit_risk_target(frame).tolist() == [True, False, False]
    assert M.management_runner_preservation_target(frame).tolist() == [False, True, False]


def test_head_subset_assigns_named_binary_classes() -> None:
    frame = pd.DataFrame(
        [
            _entry_row(trade_bucket="bad", entry_action_label="avoid_bad_entry"),
            _entry_row(trade_bucket="optimal", entry_action_label="enter_now"),
        ]
    )
    spec = next(head for head in M.HEAD_SPECS if head.name == "entry_bad_risk_head")

    subset = M.head_subset(frame, spec)

    assert subset["label_action"].tolist() == ["bad_entry_risk", "not_bad_entry_risk"]


def test_action_metrics_tracks_positive_recall() -> None:
    predictions = pd.DataFrame(
        [
            {"head_name": "entry_bad_risk_head", "oof_available_490_dual": True, "label_action": "bad_entry_risk", "predicted_action": "bad_entry_risk"},
            {"head_name": "entry_bad_risk_head", "oof_available_490_dual": True, "label_action": "bad_entry_risk", "predicted_action": "not_bad_entry_risk"},
            {"head_name": "entry_bad_risk_head", "oof_available_490_dual": True, "label_action": "not_bad_entry_risk", "predicted_action": "not_bad_entry_risk"},
        ]
    )

    actions = M.action_metrics(predictions).set_index("action")
    summary = M.summary_metrics(predictions, actions.reset_index())

    assert actions.loc["bad_entry_risk", "recall_pct"] == 50.0
    assert np.isclose(summary.loc[0, "positive_recall_pct"], 50.0)

