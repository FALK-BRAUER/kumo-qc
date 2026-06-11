from __future__ import annotations

import pandas as pd

from scripts import analyze_scanner_source_diagnostics as M


def _row(
    *,
    symbol: str,
    source_bucket: str,
    trade_bucket: str,
    ret20: float,
    mae20: float,
    reasons: str,
    date: str = "2025-01-02",
) -> dict[str, object]:
    return {
        "scan_date": date,
        "symbol": symbol,
        "opportunity_id": f"{date}|{symbol}",
        "trade_bucket": trade_bucket,
        "reason_codes": reasons,
        "source_bucket": source_bucket,
        "george_signal_seen": source_bucket in {"george_only", "both_george_and_kumo"},
        "george_video_only_context": source_bucket == "kumo_with_george_video_context",
        "kumo_signal_seen": source_bucket in {"kumo_only", "both_george_and_kumo", "kumo_with_george_video_context"},
        "kumo_top_n": source_bucket != "george_only",
        "both_george_and_kumo": source_bucket == "both_george_and_kumo",
        "george_scanner_positive": source_bucket in {"george_only", "both_george_and_kumo"},
        "george_watchlist": False,
        "george_video_mention": source_bucket == "kumo_with_george_video_context",
        "kumo_scanner": source_bucket != "george_only",
        "kumo_rank_by_score": None if source_bucket == "george_only" else 10,
        "kumo_score": None if source_bucket == "george_only" else 8.0,
        "george_rank": 2 if source_bucket in {"george_only", "both_george_and_kumo"} else None,
        "george_watchlist_rank": None,
        "company_sector": "Technology",
        "company_industry": "Software",
        "sector_category": "Technology",
        "sector_etf_proxy": "XLK",
        "source_tags": source_bucket,
        "entry_assumption_count": 4,
        "triggered_entry_count": 1,
        "strict_triggered_entry_count": 1,
        "bad_triggered_entry_count": 1 if trade_bucket == "bad" else 0,
        "best_entry_assumption": "first_hour_confirm",
        "best_entry_date": "2025-01-03",
        "best_entry_time": "2025-01-03 10:00:00",
        "best_entry_price": 10.0,
        "best_entry_ret_20d_close_pct": ret20,
        "best_entry_mfe_20d_pct": max(ret20, 0) + 4,
        "best_entry_mae_20d_pct": mae20,
        "best_entry_t4_s2_20d_outcome": "stop_before_target" if trade_bucket == "bad" else "target_before_stop",
        "best_entry_t8_s4_20d_outcome": "neither",
        "best_entry_runner_candidate_20d": trade_bucket == "optimal",
        "best_entry_normal_winner_20d": trade_bucket == "optimal",
        "best_entry_bad_trade_20d": trade_bucket == "bad",
        "best_entry_outcome_20d": trade_bucket,
        "next_open_triggered": True,
        "next_open_ret_20d_close_pct": ret20 - 1,
        "next_open_mfe_20d_pct": max(ret20, 0) + 2,
        "next_open_mae_20d_pct": mae20,
        "next_open_bad_trade_20d": trade_bucket == "bad",
        "best_deployable_exit_policy_id": "fixed_t4_s2",
        "best_deployable_exit_reason": "target" if trade_bucket == "optimal" else "stop",
        "best_deployable_exit_status": "closed",
        "best_deployable_total_equity_ret_40d_pct": ret20 / 2,
        "best_deployable_realized_ret_pct": ret20 / 2,
        "best_deployable_exposure_sessions": 3,
        "best_deployable_runner_preserved_40d": trade_bucket == "optimal",
        "oracle_best_exit_policy_id": "hold_40d_mtm",
        "oracle_best_total_equity_ret_40d_pct": ret20,
        "hold_40d_total_equity_ret_40d_pct": ret20,
        "exit_policy_entry_assumption": "next_open_path_labels",
        "feature_version": "test",
        "feature_hash": "abc",
        "oof_available": True,
        "target_trade_worthy": trade_bucket == "optimal",
        "target_runner": trade_bucket == "optimal",
        "target_fail_risk": trade_bucket == "bad",
        "baseline_kumo_rank_score": -10,
        "baseline_kumo_score": 8.0,
        "baseline_rule_score": 8.2,
        "model_trade_worthy_score": ret20,
        "model_runner_score": ret20,
        "model_combined_score": ret20,
        "classification_version": "scanner_trade_universe_v1",
    }


def _universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(
                symbol="AAA",
                source_bucket="kumo_only",
                trade_bucket="optimal",
                ret20=12.0,
                mae20=-2.0,
                reasons="realistic_entry_triggered;ret20_ge_4",
            ),
            _row(
                symbol="BBB",
                source_bucket="george_only",
                trade_bucket="optimal",
                ret20=8.0,
                mae20=-1.0,
                reasons="realistic_entry_triggered;target4_before_stop2",
            ),
            _row(
                symbol="CCC",
                source_bucket="both_george_and_kumo",
                trade_bucket="bad",
                ret20=-6.0,
                mae20=-14.0,
                reasons="realistic_entry_triggered;best_entry_bad_trade;mae20_le_minus8",
            ),
            _row(
                symbol="DDD",
                source_bucket="kumo_with_george_video_context",
                trade_bucket="optimal",
                ret20=5.0,
                mae20=-3.0,
                reasons="realistic_entry_triggered;normal_winner",
            ),
            _row(
                symbol="EEE",
                source_bucket="both_george_and_kumo",
                trade_bucket="optimal",
                ret20=7.0,
                mae20=-2.0,
                reasons="realistic_entry_triggered;normal_winner",
                date="2025-01-03",
            ),
        ]
    )


def test_source_outcome_summary_counts_trade_buckets() -> None:
    summary = M.source_outcome_summary(_universe()).set_index("source_bucket")

    assert summary.loc["kumo_only", "optimal_rows"] == 1
    assert summary.loc["george_only", "optimal_pct"] == 100.0
    assert summary.loc["both_george_and_kumo", "bad_rows"] == 1
    assert summary.loc["both_george_and_kumo", "opportunities"] == 2


def test_reason_code_summary_explodes_codes_by_source_and_bucket() -> None:
    summary = M.reason_code_summary(_universe())
    row = summary[
        (summary["source_bucket"] == "both_george_and_kumo")
        & (summary["trade_bucket"] == "bad")
        & (summary["reason_code"] == "mae20_le_minus8")
    ].iloc[0]

    assert row["rows"] == 1
    assert row["pct_of_bucket_trade"] == 100.0


def test_missed_optimal_trades_marks_side_that_missed() -> None:
    missed = M.missed_optimal_trades(_universe()).set_index("symbol")

    assert missed.loc["AAA", "missed_by"] == "george"
    assert missed.loc["BBB", "missed_by"] == "kumo"
    assert missed.loc["DDD", "missed_by"] == "george_scanner_or_watchlist"
    assert "EEE" not in set(missed.index)


def test_daily_source_examples_separates_additions_winners_and_traps() -> None:
    examples = M.daily_source_examples(_universe(), examples_per_type_date=2)

    assert "kumo_addition_optimal" in set(examples["example_type"])
    assert "george_addition_optimal" in set(examples["example_type"])
    assert "shared_trap" in set(examples["example_type"])
    assert "shared_winner" in set(examples["example_type"])
    assert "video_context_optimal" in set(examples["example_type"])


def test_denominator_diagnostics_flags_structural_missing_george_fields() -> None:
    diagnostics = M.denominator_diagnostics(_universe()).set_index("source_bucket")

    assert diagnostics.loc["george_only", "missing_kumo_rank_pct"] == 100.0
    assert diagnostics.loc["kumo_only", "missing_kumo_rank_pct"] == 0.0
    assert "Not source-comparable" in diagnostics.loc["george_only", "diagnostic_note"]
