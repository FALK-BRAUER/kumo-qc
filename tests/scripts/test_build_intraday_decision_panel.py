from __future__ import annotations

import pandas as pd

from scripts import build_intraday_decision_panel as M


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "_dt": pd.Timestamp("2025-01-02 09:30:00"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 1000.0,
            },
            {
                "symbol": "AAA",
                "_dt": pd.Timestamp("2025-01-02 09:35:00"),
                "open": 100.5,
                "high": 102.0,
                "low": 100.0,
                "close": 101.5,
                "volume": 1500.0,
            },
            {
                "symbol": "AAA",
                "_dt": pd.Timestamp("2025-01-02 09:40:00"),
                "open": 101.5,
                "high": 103.0,
                "low": 101.0,
                "close": 102.5,
                "volume": 2000.0,
            },
            {
                "symbol": "AAA",
                "_dt": pd.Timestamp("2025-01-02 09:45:00"),
                "open": 102.5,
                "high": 104.0,
                "low": 102.0,
                "close": 103.5,
                "volume": 2500.0,
            },
        ]
    )


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "scan_date": "2025-01-01",
        "entry_session_date": "2025-01-02",
        "symbol": "AAA",
        "opportunity_id": "2025-01-01|AAA",
        "trade_bucket": "optimal",
        "source_bucket": "kumo_only",
        "reason_codes": "",
        "kumo_signal_seen": True,
        "kumo_top_n": True,
        "kumo_scanner": True,
        "kumo_rank_by_score": 5.0,
        "kumo_score": 8.0,
        "george_signal_seen": False,
        "george_scanner_positive": False,
        "george_watchlist": False,
        "george_video_mention": False,
        "best_entry_assumption": "next_open",
        "best_entry_time": "2025-01-02 09:30:00",
        "best_entry_price": 100.0,
        "best_entry_runner_candidate_20d": True,
        "best_entry_bad_trade_20d": False,
        "best_deployable_runner_preserved_40d": True,
        "triggered_entry_assumptions": 2,
        "bad_entry_assumptions": 0,
    }
    base.update(overrides)
    return base


def test_completed_bars_treats_timestamp_as_five_minute_bar_start() -> None:
    done = M.completed_bars(_bars(), pd.Timestamp("2025-01-02 09:45:00"))

    assert done["_dt"].tolist() == [
        pd.Timestamp("2025-01-02 09:30:00"),
        pd.Timestamp("2025-01-02 09:35:00"),
        pd.Timestamp("2025-01-02 09:40:00"),
    ]


def test_asof_features_do_not_use_unclosed_bar() -> None:
    features = M.asof_features(bars=_bars(), as_of=pd.Timestamp("2025-01-02 09:45:00"), prior_close=99.0)

    assert features["bars_completed"] == 3
    assert features["current_price"] == 102.5
    assert features["last_15m_available"] is True
    assert features["last_hour_available"] is False


def test_entry_action_label_waits_until_best_entry_time() -> None:
    record = _record(best_entry_time="2025-01-02 10:00:00")

    before, _ = M.entry_action_label(record, as_of=pd.Timestamp("2025-01-02 09:45:00"))
    after, _ = M.entry_action_label(record, as_of=pd.Timestamp("2025-01-02 10:00:00"))
    bad, _ = M.entry_action_label(_record(trade_bucket="bad"), as_of=pd.Timestamp("2025-01-02 09:45:00"))

    assert before == "wait"
    assert after == "enter_now"
    assert bad == "avoid_bad_entry"


def test_rows_for_candidate_separates_entry_and_position_rows() -> None:
    rows = M.rows_for_candidate(
        _record(),
        symbol_bars=_bars(),
        etf_bars=pd.DataFrame(),
        checkpoints=(("open", "09:30:00"), ("after_15m", "09:45:00")),
    )
    frame = pd.DataFrame(rows)

    assert frame["row_type"].tolist() == [
        "entry_decision",
        "position_management",
        "entry_decision",
        "position_management",
    ]
    assert frame.loc[0, "entry_action_label"] == "enter_now"
    assert frame.loc[1, "management_action_label"] == "hold_winner"
    assert frame.loc[3, "position_bars_completed_since_entry"] == 2


def test_rows_for_candidate_handles_missing_next_calendar_date() -> None:
    record = _record(entry_session_date="", trade_bucket="optimal")

    rows = M.rows_for_candidate(
        record,
        symbol_bars=pd.DataFrame(),
        etf_bars=pd.DataFrame(),
        checkpoints=(("open", "09:30:00"),),
    )

    assert len(rows) == 1
    assert rows[0]["entry_action_label"] == "missing_intraday"
    assert rows[0]["intraday_available"] is False


def test_label_summary_keeps_entry_and_management_actions_separate() -> None:
    frame = pd.DataFrame(
        [
            {"row_type": "entry_decision", "entry_action_label": "enter_now", "management_action_label": "", "symbol": "AAA", "scan_date": "2025-01-01"},
            {"row_type": "entry_decision", "entry_action_label": "wait", "management_action_label": "", "symbol": "BBB", "scan_date": "2025-01-01"},
            {"row_type": "position_management", "entry_action_label": "", "management_action_label": "hold_winner", "symbol": "AAA", "scan_date": "2025-01-01"},
        ]
    )

    summary = M.label_summary(frame)

    assert set(summary["row_type"]) == {"entry_decision", "position_management"}
    assert set(summary["action_label"]) == {"enter_now", "wait", "hold_winner"}
