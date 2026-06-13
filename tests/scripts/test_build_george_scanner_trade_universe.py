from __future__ import annotations

import pandas as pd

from scripts import build_george_scanner_trade_universe as M


def _panel(
    *,
    symbol: str,
    george: bool,
    watchlist: bool = False,
    video: bool = False,
    kumo: bool = False,
) -> dict[str, object]:
    return {
        "scan_date": "2025-01-02",
        "symbol": symbol,
        "opportunity_id": f"2025-01-02|{symbol}",
        "kumo_scanner": kumo,
        "kumo_top_n": kumo,
        "george_scanner_positive": george,
        "george_watchlist": watchlist,
        "george_video_mention": video,
        "kumo_rank_by_score": 7 if kumo else None,
        "kumo_score": 8.5 if kumo else None,
        "george_rank": 2 if george else None,
        "george_watchlist_rank": 1 if watchlist else None,
        "company_sector": "Technology",
        "company_industry": "Software",
        "sector_category": "Technology",
        "sector_etf_proxy": "XLK",
        "source_tags": "test",
    }


def _entry(
    *,
    symbol: str,
    entry_assumption: str = "first_hour_confirm",
    triggered: bool,
    ret20: float | None,
    mfe20: float | None,
    mae20: float | None,
    george: bool,
    watchlist: bool = False,
    video: bool = False,
    kumo: bool = False,
    bad: bool = False,
    normal: bool = False,
    runner: bool = False,
    t4s2: str = "neither",
) -> dict[str, object]:
    return {
        "scan_date": "2025-01-02",
        "symbol": symbol,
        "opportunity_id": f"2025-01-02|{symbol}",
        "kumo_scanner": kumo,
        "kumo_top_n": kumo,
        "george_scanner_positive": george,
        "george_watchlist": watchlist,
        "george_video_mention": video,
        "kumo_rank_by_score": 7 if kumo else None,
        "kumo_score": 8.5 if kumo else None,
        "george_rank": 2 if george else None,
        "george_watchlist_rank": 1 if watchlist else None,
        "source_tags": "test",
        "entry_assumption": entry_assumption,
        "label_entry_date": "2025-01-03" if triggered else "",
        "label_entry_time": "2025-01-03 10:00:00" if triggered else "",
        "label_entry_price": 10.0 if triggered else None,
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


def _exit(
    *,
    symbol: str,
    policy_id: str,
    total40: float,
    runner_preserved: bool = False,
) -> dict[str, object]:
    return {
        "opportunity_id": f"2025-01-02|{symbol}",
        "policy_id": policy_id,
        "deployability": "lean_and_qc_ready",
        "policy_status": "closed",
        "exit_reason": "target" if total40 > 0 else "stop",
        "total_equity_ret_40d_pct": total40,
        "realized_ret_pct": total40,
        "exposure_sessions": 4,
        "runner_preserved_40d": runner_preserved,
    }


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    panel = pd.DataFrame(
        [
            _panel(symbol="AAA", george=True),
            _panel(symbol="BBB", george=True, kumo=True),
            _panel(symbol="CCC", george=False, video=True),
            _panel(symbol="DDD", george=True),
            _panel(symbol="EEE", george=True, video=True),
        ]
    )
    entries = pd.DataFrame(
        [
            _entry(
                symbol="AAA",
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
                triggered=True,
                ret20=-9.0,
                mfe20=1.0,
                mae20=-12.0,
                george=True,
                kumo=True,
                bad=True,
                t4s2="stop_before_target",
            ),
            _entry(
                symbol="CCC",
                triggered=True,
                ret20=20.0,
                mfe20=25.0,
                mae20=-1.0,
                george=False,
                video=True,
                normal=True,
                t4s2="target_before_stop",
            ),
            _entry(
                symbol="DDD",
                triggered=False,
                ret20=None,
                mfe20=None,
                mae20=None,
                george=True,
            ),
            _entry(
                symbol="EEE",
                triggered=True,
                ret20=5.0,
                mfe20=7.0,
                mae20=-1.0,
                george=True,
                video=True,
                normal=True,
                t4s2="target_before_stop",
            ),
        ]
    )
    exits = pd.DataFrame(
        [
            _exit(symbol="AAA", policy_id="fixed_t4_s2", total40=5.0),
            _exit(symbol="BBB", policy_id="fixed_t4_s2", total40=-7.0),
            _exit(symbol="EEE", policy_id="fixed_t4_s2", total40=4.0),
        ]
    )
    return entries, panel, exits


def test_build_george_trade_universe_filters_denominator_and_classifies_rows() -> None:
    entries, panel, exits = _fixture()

    universe = M.build_george_trade_universe(entries=entries, panel=panel, exits=exits)
    indexed = universe.set_index("symbol")

    assert set(indexed.index) == {"AAA", "BBB", "DDD", "EEE"}
    assert indexed.loc["AAA", "source_bucket"] == "george_only"
    assert indexed.loc["AAA", "trade_bucket"] == "optimal"
    assert pd.isna(indexed.loc["AAA", "kumo_rank_by_score"])
    assert indexed.loc["BBB", "source_bucket"] == "both_george_and_kumo"
    assert indexed.loc["BBB", "trade_bucket"] == "bad"
    assert indexed.loc["DDD", "trade_bucket"] == "watch"
    assert "no_realistic_entry_triggered" in indexed.loc["DDD", "reason_codes"]
    assert indexed.loc["EEE", "source_bucket"] == "george_with_video_context"
    assert bool(indexed.loc["EEE", "trainable_scanner_evidence"])


def test_video_only_context_is_excluded_but_counted_in_coverage() -> None:
    entries, panel, exits = _fixture()
    universe = M.build_george_trade_universe(entries=entries, panel=panel, exits=exits)

    coverage = M.coverage_summary(panel, entries, exits, universe).set_index("category")

    assert coverage.loc["george_scanner_or_watchlist_candidates", "opportunities"] == 4
    assert coverage.loc["video_only_context_excluded", "opportunities"] == 1
    assert coverage.loc["video_only_context_excluded", "in_universe"] == 0
    assert not bool(coverage.loc["video_only_context_excluded", "trainable_scanner_evidence"])
    assert coverage.loc["candidate_missing_exit_policy_labels", "opportunities"] == 1
    assert coverage.loc["universe_no_realistic_entry", "opportunities"] == 1


def test_source_and_reason_summaries_capture_missing_kumo_without_penalty() -> None:
    entries, panel, exits = _fixture()
    universe = M.build_george_trade_universe(entries=entries, panel=panel, exits=exits)

    source = M.source_summary(universe).set_index("source_bucket")
    reasons = M.reason_code_summary(universe)

    assert source.loc["george_only", "missing_kumo_rank_pct"] == 100.0
    assert source.loc["george_only", "optimal_rows"] == 1
    assert source.loc["george_only", "watch_rows"] == 1
    bad_reason = reasons[
        (reasons["source_bucket"] == "both_george_and_kumo")
        & (reasons["trade_bucket"] == "bad")
        & (reasons["reason_code"] == "mae20_le_minus8")
    ].iloc[0]
    assert bad_reason["rows"] == 1


def test_training_readiness_uses_labeled_optimal_and_bad_counts() -> None:
    entries, panel, exits = _fixture()
    universe = M.build_george_trade_universe(entries=entries, panel=panel, exits=exits)

    readiness = M.training_readiness(universe, min_class_rows=1)

    assert readiness["optimal_rows"] == 2
    assert readiness["bad_rows"] == 1
    assert readiness["ready_for_george_model"]
