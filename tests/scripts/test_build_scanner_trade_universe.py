from __future__ import annotations

import pandas as pd

from scripts import build_scanner_trade_universe as M


def _entry(
    *,
    symbol: str,
    entry_assumption: str,
    triggered: bool,
    ret20: float | None,
    mfe20: float | None,
    mae20: float | None,
    bad: bool = False,
    runner: bool = False,
    normal: bool = False,
    t4s2: str = "neither",
    george: bool = False,
    kumo: bool = True,
) -> dict[str, object]:
    return {
        "scan_date": "2025-01-02",
        "symbol": symbol,
        "opportunity_id": f"2025-01-02|{symbol}",
        "kumo_scanner": kumo,
        "kumo_top_n": kumo,
        "george_scanner_positive": george,
        "george_watchlist": False,
        "george_video_mention": False,
        "kumo_rank_by_score": 12,
        "kumo_score": 8.0,
        "george_rank": 2 if george else None,
        "george_watchlist_rank": None,
        "source_tags": "kumo_scanner;kumo_top_n",
        "entry_assumption": entry_assumption,
        "label_entry_date": "2025-01-03",
        "label_entry_time": "2025-01-03 10:00:00" if entry_assumption != "next_open" else "2025-01-03 09:30:00",
        "label_entry_price": 10.0,
        "label_triggered": triggered,
        "label_trigger_status": "triggered" if triggered else "no_entry_trigger",
        "label_trigger_reason": "test",
        "label_path_status": "available_full_40d" if triggered else "no_entry_trigger",
        "label_ret_20d_close_pct": ret20,
        "label_mfe_20d_pct": mfe20,
        "label_mae_20d_pct": mae20,
        "label_t4_s2_20d_outcome": t4s2,
        "label_t8_s4_20d_outcome": "neither",
        "label_runner_candidate_20d": runner,
        "label_normal_winner_20d": normal,
        "label_bad_trade_20d": bad,
        "label_extreme_path_flag": False,
        "label_outcome_20d": "bad_trade" if bad else "normal_winner" if normal else "chop_or_unclear",
    }


def test_select_best_entry_uses_return_mfe_and_mae_tiebreaks() -> None:
    group = pd.DataFrame(
        [
            _entry(symbol="AAA", entry_assumption="next_open", triggered=True, ret20=5.0, mfe20=8.0, mae20=-2.0),
            _entry(
                symbol="AAA",
                entry_assumption="first_hour_confirm",
                triggered=True,
                ret20=7.0,
                mfe20=6.0,
                mae20=-1.0,
            ),
            _entry(
                symbol="AAA",
                entry_assumption="prior_session_high_breakout",
                triggered=False,
                ret20=20.0,
                mfe20=25.0,
                mae20=-1.0,
            ),
        ]
    )

    best = M.select_best_entry(group)

    assert best is not None
    assert best["entry_assumption"] == "first_hour_confirm"


def test_aggregate_exits_selects_best_deployable_and_oracle() -> None:
    exits = pd.DataFrame(
        [
            {
                "opportunity_id": "2025-01-02|AAA",
                "policy_id": "hold_40d_mtm",
                "deployability": "research_baseline",
                "policy_status": "open_at_horizon",
                "exit_reason": "horizon_mtm",
                "total_equity_ret_40d_pct": 9.0,
                "realized_ret_pct": 0.0,
                "exposure_sessions": 40,
                "runner_preserved_40d": True,
            },
            {
                "opportunity_id": "2025-01-02|AAA",
                "policy_id": "fixed_t4_s2",
                "deployability": "lean_and_qc_ready",
                "policy_status": "closed",
                "exit_reason": "target",
                "total_equity_ret_40d_pct": 4.0,
                "realized_ret_pct": 4.0,
                "exposure_sessions": 2,
                "runner_preserved_40d": False,
            },
            {
                "opportunity_id": "2025-01-02|AAA",
                "policy_id": "giveback35_after8",
                "deployability": "lean_and_qc_ready",
                "policy_status": "closed",
                "exit_reason": "giveback_stop",
                "total_equity_ret_40d_pct": 6.0,
                "realized_ret_pct": 6.0,
                "exposure_sessions": 8,
                "runner_preserved_40d": True,
            },
        ]
    )

    summary = M.aggregate_exits(exits).set_index("opportunity_id")
    row = summary.loc["2025-01-02|AAA"]

    assert row["best_deployable_exit_policy_id"] == "giveback35_after8"
    assert row["best_deployable_total_equity_ret_40d_pct"] == 6.0
    assert row["oracle_best_exit_policy_id"] == "hold_40d_mtm"
    assert row["hold_40d_total_equity_ret_40d_pct"] == 9.0


def test_classify_trade_marks_optimal_and_bad_paths() -> None:
    optimal = pd.Series(
        {
            "george_signal_seen": True,
            "kumo_signal_seen": True,
            "triggered_entry_count": 1,
            "best_entry_ret_20d_close_pct": 6.0,
            "best_entry_mfe_20d_pct": 9.0,
            "best_entry_mae_20d_pct": -2.0,
            "best_entry_t4_s2_20d_outcome": "target_before_stop",
            "best_entry_bad_trade_20d": False,
            "best_entry_runner_candidate_20d": False,
            "best_entry_normal_winner_20d": True,
            "best_deployable_exit_total_equity_ret_40d_pct": 5.0,
        }
    )
    bad = optimal.copy()
    bad["best_entry_bad_trade_20d"] = True
    bad["best_entry_mae_20d_pct"] = -12.0
    bad["best_entry_t4_s2_20d_outcome"] = "stop_before_target"

    assert M.classify_trade(optimal)[0] == "optimal"
    bucket, reasons = M.classify_trade(bad)
    assert bucket == "bad"
    assert "best_entry_bad_trade" in reasons
    assert "mae20_le_minus8" in reasons


def test_build_trade_universe_joins_sources_and_summaries() -> None:
    entries = pd.DataFrame(
        [
            _entry(
                symbol="AAA",
                entry_assumption="next_open",
                triggered=True,
                ret20=2.0,
                mfe20=5.0,
                mae20=-1.0,
                george=True,
                normal=True,
            ),
            _entry(
                symbol="AAA",
                entry_assumption="first_hour_confirm",
                triggered=True,
                ret20=6.0,
                mfe20=9.0,
                mae20=-2.0,
                george=True,
                normal=True,
                t4s2="target_before_stop",
            ),
            _entry(
                symbol="BBB",
                entry_assumption="next_open",
                triggered=True,
                ret20=-9.0,
                mfe20=1.0,
                mae20=-12.0,
                bad=True,
                t4s2="stop_before_target",
            ),
            _entry(
                symbol="BBB",
                entry_assumption="first_hour_confirm",
                triggered=False,
                ret20=None,
                mfe20=None,
                mae20=None,
            ),
        ]
    )
    panel = pd.DataFrame(
        [
            {
                "opportunity_id": "2025-01-02|AAA",
                "company_sector": "Technology",
                "company_industry": "Software",
                "sector_category": "Technology",
                "sector_etf_proxy": "XLK",
            },
            {
                "opportunity_id": "2025-01-02|BBB",
                "company_sector": "Healthcare",
                "company_industry": "Biotech",
                "sector_category": "Healthcare",
                "sector_etf_proxy": "XLV",
            },
        ]
    )
    exits = pd.DataFrame(
        [
            {
                "opportunity_id": "2025-01-02|AAA",
                "policy_id": "fixed_t4_s2",
                "deployability": "lean_and_qc_ready",
                "policy_status": "closed",
                "exit_reason": "target",
                "total_equity_ret_40d_pct": 4.0,
                "realized_ret_pct": 4.0,
                "exposure_sessions": 2,
                "runner_preserved_40d": False,
            },
            {
                "opportunity_id": "2025-01-02|BBB",
                "policy_id": "fixed_t4_s2",
                "deployability": "lean_and_qc_ready",
                "policy_status": "closed",
                "exit_reason": "stop",
                "total_equity_ret_40d_pct": -7.0,
                "realized_ret_pct": -7.0,
                "exposure_sessions": 1,
                "runner_preserved_40d": False,
            },
        ]
    )
    ranker = pd.DataFrame(
        [
            {
                "opportunity_id": "2025-01-02|AAA",
                "feature_version": "test",
                "feature_hash": "abc",
                "oof_available": True,
                "model_combined_score": 0.9,
            }
        ]
    )

    universe = M.build_trade_universe(entries=entries, panel=panel, exits=exits, ranker=ranker)
    indexed = universe.set_index("symbol")

    assert indexed.loc["AAA", "trade_bucket"] == "optimal"
    assert indexed.loc["AAA", "source_bucket"] == "both_george_and_kumo"
    assert indexed.loc["AAA", "best_entry_assumption"] == "first_hour_confirm"
    assert indexed.loc["BBB", "trade_bucket"] == "bad"
    assert indexed.loc["BBB", "source_bucket"] == "kumo_only"

    summary = M.source_summary(universe).set_index("source_bucket")
    assert summary.loc["both_george_and_kumo", "optimal_rows"] == 1
    assert summary.loc["kumo_only", "bad_rows"] == 1
