from __future__ import annotations

import numpy as np
import pandas as pd

from scripts import replay_intraday_entry_exit_policy as M
from scripts import train_intraday_entry_exit_policy as T


def _entry_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "scan_date": "2025-01-01",
        "entry_session_date": "2025-01-02",
        "symbol": "AAA",
        "opportunity_id": "2025-01-01|AAA",
        "row_type": "entry_decision",
        "checkpoint": "open",
        "checkpoint_order": 0,
        "as_of_timestamp": "2025-01-02 09:30:00",
        "scanner_source_bucket": "kumo_only",
        "trade_bucket": "optimal",
        "oracle_best_entry_outcome_20d": "runner_candidate",
        "oracle_best_deployable_total_equity_ret_40d_pct": 8.0,
        "kumo_rank_by_score": 5.0,
        "kumo_score": 8.0,
        "george_signal_seen": False,
        "entry_action_label": "wait",
        "management_action_label": "",
        "intraday_available": True,
        "last_15m_available": False,
        "last_hour_available": False,
        "etf_intraday_available": False,
        "etf_last_15m_available": False,
        "etf_last_hour_available": False,
        "ichimoku_15m_available": False,
        "ichimoku_hour_available": False,
        "etf_ichimoku_15m_available": False,
        "etf_ichimoku_hour_available": False,
        "current_price": 100.0,
        "return_from_open_pct": 0.0,
        "mae_from_open_pct": 0.0,
        "mfe_from_open_pct": 0.0,
        "distance_from_vwap_pct": 0.0,
    }
    row.update(overrides)
    return row


def _feature_names() -> list[str]:
    _out, features = T.add_policy_features(pd.DataFrame([_entry_row()]))
    return features


def _policy_artifact(*, entry_intercept: list[float], management_intercept: list[float]) -> dict[str, object]:
    features = _feature_names()

    def fold(classes: tuple[str, ...], intercept: list[float]) -> dict[str, object]:
        return {
            "fold": 1,
            "valid_start": "2025-01-01",
            "valid_end": "2025-12-31",
            "standardizer": {"mean": [0.0] * len(features), "scale": [1.0] * len(features)},
            "coef": [[0.0] * len(classes) for _ in features],
            "intercept": intercept,
        }

    return {
        "policies": {
            "entry_policy": {
                "feature_names": features,
                "classes": list(T.ENTRY_ACTIONS),
                "fold_models": [fold(T.ENTRY_ACTIONS, entry_intercept)],
            },
            "management_policy": {
                "feature_names": features,
                "classes": list(T.MANAGEMENT_ACTIONS),
                "fold_models": [fold(T.MANAGEMENT_ACTIONS, management_intercept)],
            },
        }
    }


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": "AAA", "_dt": pd.Timestamp("2025-01-02 09:30:00"), "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 1000.0},
            {"symbol": "AAA", "_dt": pd.Timestamp("2025-01-02 09:35:00"), "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 1000.0},
            {"symbol": "AAA", "_dt": pd.Timestamp("2025-01-02 09:40:00"), "open": 101.5, "high": 103.0, "low": 101.0, "close": 102.5, "volume": 1000.0},
        ]
    )


def test_score_policy_rows_uses_oof_fold_intercept() -> None:
    artifact = _policy_artifact(entry_intercept=[0.0, 5.0, 0.0], management_intercept=[0.0, 5.0, 0.0, 0.0, 0.0, 0.0])
    scored = M.score_policy_rows(pd.DataFrame([_entry_row()]), artifact, "entry_policy")

    assert scored.loc[0, "policy_oof_available"] is np.True_ or scored.loc[0, "policy_oof_available"] is True
    assert scored.loc[0, "policy_action"] == "enter_now"
    assert scored.loc[0, "policy_fold"] == 1


def test_selected_entries_picks_first_enter_now_checkpoint() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(checkpoint="open", checkpoint_order=0, entry_model_available=True, entry_model_action="wait"),
            _entry_row(checkpoint="after_15m", checkpoint_order=1, as_of_timestamp="2025-01-02 09:45:00", entry_model_available=True, entry_model_action="enter_now", current_price=102.5),
            _entry_row(checkpoint="after_30m", checkpoint_order=2, as_of_timestamp="2025-01-02 10:00:00", entry_model_available=True, entry_model_action="enter_now", current_price=103.0),
        ]
    )

    selected = M.selected_entries(rows, variant="model_policy")

    assert bool(selected.loc[0, "entered"]) is True
    assert selected.loc[0, "entry_checkpoint"] == "after_15m"
    assert selected.loc[0, "entry_price"] == 102.5


def test_entry_policy_v2_preserves_baseline_enter_when_risk_is_not_decisive() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                entry_model_action="avoid_bad_entry",
                baseline_entry_action="enter_now",
                policy_prob_avoid_bad_entry=0.30,
                policy_prob_enter_now=0.25,
                return_from_open_pct=0.2,
                mae_from_open_pct=-0.5,
            )
        ]
    )

    action = M.entry_policy_v2_action(rows)

    assert action.loc[0] == "enter_now"


def test_entry_policy_v2_keeps_avoid_when_risk_is_decisive() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                entry_model_action="avoid_bad_entry",
                baseline_entry_action="enter_now",
                policy_prob_avoid_bad_entry=0.72,
                policy_prob_enter_now=0.10,
                return_from_open_pct=1.0,
                mae_from_open_pct=-0.2,
            )
        ]
    )

    action = M.entry_policy_v2_action(rows)

    assert action.loc[0] == "avoid_bad_entry"


def test_entry_policy_v3_preserves_scan_confirmed_winner() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                entry_model_action="avoid_bad_entry",
                baseline_entry_action="enter_now",
                entry_policy_v2_action="avoid_bad_entry",
                policy_prob_avoid_bad_entry=0.38,
                policy_prob_enter_now=0.26,
                return_from_open_pct=0.4,
                mae_from_open_pct=-0.4,
                oof_available_492=True,
                model_492_optimal_score=0.20,
                model_492_bad_risk_score=-0.30,
            )
        ]
    )

    action = M.entry_policy_v3_action(rows)

    assert action.loc[0] == "enter_now"


def test_entry_policy_v3_rejects_recovery_when_scan_bad_risk_is_not_clean() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                entry_model_action="avoid_bad_entry",
                baseline_entry_action="enter_now",
                entry_policy_v2_action="avoid_bad_entry",
                policy_prob_avoid_bad_entry=0.38,
                policy_prob_enter_now=0.26,
                return_from_open_pct=1.0,
                mae_from_open_pct=-0.1,
                oof_available_492=True,
                model_492_optimal_score=0.45,
                model_492_bad_risk_score=0.10,
            )
        ]
    )

    action = M.entry_policy_v3_action(rows)

    assert action.loc[0] == "avoid_bad_entry"


def test_dual_head_entry_action_enters_when_risk_winner_and_ready_agree() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                baseline_entry_action="wait",
                entry_bad_risk_available=True,
                entry_winner_preservation_available=True,
                entry_ready_available=True,
                entry_bad_risk_prob_bad_entry_risk=0.30,
                entry_winner_preservation_prob_winner_preserve=0.62,
                entry_ready_prob_entry_ready=0.55,
            )
        ]
    )

    action = M.dual_head_entry_action(rows)

    assert action.loc[0] == "enter_now"


def test_dual_head_entry_action_avoids_when_bad_risk_dominates() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                baseline_entry_action="enter_now",
                entry_bad_risk_available=True,
                entry_winner_preservation_available=True,
                entry_ready_available=True,
                entry_bad_risk_prob_bad_entry_risk=0.72,
                entry_winner_preservation_prob_winner_preserve=0.40,
                entry_ready_prob_entry_ready=0.60,
            )
        ]
    )

    action = M.dual_head_entry_action(rows)

    assert action.loc[0] == "avoid_bad_entry"


def test_dual_head_management_action_preserves_runner_before_exit_risk() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                management_exit_risk_available=True,
                management_runner_preservation_available=True,
                management_exit_risk_prob_exit_risk=0.80,
                management_runner_preservation_prob_runner_preserve=0.70,
                position_current_return_pct=5.0,
                position_drawdown_from_peak_pct=2.0,
            )
        ]
    )

    action = M.dual_head_management_action(rows)

    assert action.loc[0] == "do_not_cut_runner"


def test_selected_entries_supports_entry_policy_v2_variant() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(checkpoint="open", checkpoint_order=0, entry_model_available=True, entry_policy_v2_action="wait"),
            _entry_row(
                checkpoint="after_15m",
                checkpoint_order=1,
                as_of_timestamp="2025-01-02 09:45:00",
                entry_model_available=True,
                entry_policy_v2_action="enter_now",
                current_price=102.5,
            ),
        ]
    )

    selected = M.selected_entries(rows, variant=M.ENTRY_POLICY_V2_VARIANT)

    assert bool(selected.loc[0, "entered"]) is True
    assert selected.loc[0, "entry_checkpoint"] == "after_15m"


def test_selected_entries_supports_entry_policy_v3_variant() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(checkpoint="open", checkpoint_order=0, entry_model_available=True, entry_policy_v3_action="wait"),
            _entry_row(
                checkpoint="after_15m",
                checkpoint_order=1,
                as_of_timestamp="2025-01-02 09:45:00",
                entry_model_available=True,
                entry_policy_v3_action="enter_now",
                current_price=102.5,
                oof_available_492=True,
                model_492_optimal_score=0.4,
                model_492_bad_risk_score=0.2,
            ),
        ]
    )

    selected = M.selected_entries(rows, variant=M.ENTRY_POLICY_V3_VARIANT)

    assert bool(selected.loc[0, "entered"]) is True
    assert selected.loc[0, "entry_checkpoint"] == "after_15m"
    assert selected.loc[0, "entry_scan_time_optimal_score"] == 0.4


def test_selected_entries_supports_dual_head_variant() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(checkpoint="open", checkpoint_order=0, entry_model_available=True, dual_head_entry_action="wait"),
            _entry_row(
                checkpoint="after_15m",
                checkpoint_order=1,
                as_of_timestamp="2025-01-02 09:45:00",
                entry_model_available=True,
                dual_head_entry_action="enter_now",
                current_price=102.5,
                entry_bad_risk_prob_bad_entry_risk=0.2,
                entry_winner_preservation_prob_winner_preserve=0.7,
                entry_ready_prob_entry_ready=0.8,
            ),
        ]
    )

    selected = M.selected_entries(rows, variant=M.DUAL_HEAD_VARIANT)

    assert bool(selected.loc[0, "entered"]) is True
    assert selected.loc[0, "entry_checkpoint"] == "after_15m"
    assert selected.loc[0, "entry_dual_winner_preserve_prob"] == 0.7


def test_build_management_decision_rows_reconstructs_position_features(monkeypatch) -> None:
    entry_rows = pd.DataFrame(
        [
            _entry_row(checkpoint="open", checkpoint_order=0, as_of_timestamp="2025-01-02 09:30:00", current_price=100.0),
            _entry_row(checkpoint="after_15m", checkpoint_order=1, as_of_timestamp="2025-01-02 09:45:00", current_price=102.5),
        ]
    )
    selected = pd.DataFrame(
        [
            {
                "variant": "model_policy",
                "opportunity_id": "2025-01-01|AAA",
                "entry_session_date": "2025-01-02",
                "symbol": "AAA",
                "entered": True,
                "entry_checkpoint": "open",
                "entry_checkpoint_order": 0,
                "entry_timestamp": "2025-01-02 09:30:00",
                "entry_price": 100.0,
            }
        ]
    )
    monkeypatch.setattr(M, "_read_day_symbol_bars", lambda _root, _day, _symbols: {"AAA": _bars()})

    management = M.build_management_decision_rows(entry_rows, selected, parquet_root=M.DEFAULT_PARQUET_ROOT)

    assert management["checkpoint"].tolist() == ["after_15m"]
    after_15m = management[management["checkpoint"].eq("after_15m")].iloc[0]
    assert after_15m["position_bars_completed_since_entry"] == 2
    assert after_15m["position_current_return_pct"] == 2.5
    assert after_15m["position_mfe_so_far_pct"] == 3.0


def test_entry_policy_v2_uses_model_management_actions() -> None:
    rows = pd.DataFrame(
        [
            _entry_row(
                variant=M.ENTRY_POLICY_V2_VARIANT,
                row_type="position_management",
                management_action_label="",
                checkpoint="after_15m",
                checkpoint_order=1,
            )
        ]
    )
    artifact = _policy_artifact(
        entry_intercept=[0.0, 5.0, 0.0],
        management_intercept=[0.0, 5.0, 0.0, 0.0, 0.0, 0.0],
    )

    scored = M.add_management_actions(rows, artifact)

    assert bool(scored.loc[0, "management_model_available"]) is True
    assert scored.loc[0, "management_model_action"] == "exit_loser"


def test_finalize_candidate_outcomes_exits_on_first_policy_exit() -> None:
    selected = pd.DataFrame(
        [
            {
                "variant": "model_policy",
                "opportunity_id": "2025-01-01|AAA",
                "scan_date": "2025-01-01",
                "entry_session_date": "2025-01-02",
                "symbol": "AAA",
                "scanner_source_bucket": "kumo_only",
                "trade_bucket": "bad",
                "oracle_best_entry_outcome_20d": "bad_trade",
                "eligible": True,
                "entered": True,
                "entry_checkpoint": "open",
                "entry_checkpoint_order": 0,
                "entry_timestamp": "2025-01-02 09:30:00",
                "entry_price": 100.0,
            }
        ]
    )
    management = pd.DataFrame(
        [
            {"variant": "model_policy", "opportunity_id": "2025-01-01|AAA", "checkpoint": "open", "checkpoint_order": 0, "as_of_timestamp": "2025-01-02 09:30:00", "current_price": 100.0, "management_model_available": True, "management_model_action": "hold_or_wait", "position_minutes_since_entry": 0, "position_current_return_pct": 0.0, "position_mfe_so_far_pct": 0.0, "position_mae_so_far_pct": 0.0, "position_drawdown_from_peak_pct": 0.0},
            {"variant": "model_policy", "opportunity_id": "2025-01-01|AAA", "checkpoint": "after_15m", "checkpoint_order": 1, "as_of_timestamp": "2025-01-02 09:45:00", "current_price": 98.0, "management_model_available": True, "management_model_action": "exit_loser", "management_model_confidence": 0.9, "position_minutes_since_entry": 15, "position_current_return_pct": -2.0, "position_mfe_so_far_pct": 0.0, "position_mae_so_far_pct": -2.5, "position_drawdown_from_peak_pct": 2.0},
        ]
    )

    outcomes = M.finalize_candidate_outcomes(selected, management)

    assert outcomes.loc[0, "exit_checkpoint"] == "after_15m"
    assert outcomes.loc[0, "exit_action"] == "exit_loser"
    assert outcomes.loc[0, "realized_intraday_ret_pct"] == -2.0


def test_summary_metrics_tracks_bad_and_optimal_entry_rates() -> None:
    outcomes = pd.DataFrame(
        [
            {"variant": "baseline_rules", "eligible": True, "entered": True, "trade_bucket": "bad", "is_bad_bucket": True, "is_optimal_bucket": False, "is_runner_candidate": False, "realized_intraday_ret_pct": -1.0, "mfe_intraday_pct": 0.0, "mae_intraday_pct": -1.5, "exit_action": "exit_loser"},
            {"variant": "baseline_rules", "eligible": True, "entered": False, "trade_bucket": "optimal", "is_bad_bucket": False, "is_optimal_bucket": True, "is_runner_candidate": True, "realized_intraday_ret_pct": np.nan, "mfe_intraday_pct": np.nan, "mae_intraday_pct": np.nan, "exit_action": ""},
            {"variant": "baseline_rules", "eligible": True, "entered": True, "trade_bucket": "optimal", "is_bad_bucket": False, "is_optimal_bucket": True, "is_runner_candidate": True, "realized_intraday_ret_pct": 2.0, "mfe_intraday_pct": 3.0, "mae_intraday_pct": -0.5, "exit_action": "close_mark"},
        ]
    )

    summary = M.summary_metrics(outcomes).set_index("variant")

    assert summary.loc["baseline_rules", "trades"] == 2
    assert summary.loc["baseline_rules", "bad_entry_rate_pct"] == 100.0
    assert summary.loc["baseline_rules", "optimal_entry_rate_pct"] == 50.0
    assert summary.loc["baseline_rules", "win_rate_pct"] == 50.0
