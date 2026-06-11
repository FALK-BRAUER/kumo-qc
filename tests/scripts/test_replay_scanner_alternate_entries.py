from __future__ import annotations

import pandas as pd

from scripts import replay_scanner_alternate_entries as M


def _bar(time: str, open_: float, high: float, low: float, close: float) -> M.IntradayBar:
    return M.IntradayBar(
        symbol="AAA",
        day="2025-01-02",
        timestamp=f"2025-01-02 {time}",
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


def test_first_hour_confirm_enters_at_first_hour_close_and_excludes_pre_entry_bars() -> None:
    bars = [
        _bar("09:30:00", 100, 101, 99, 100.5),
        _bar("10:25:00", 100.5, 102, 100, 101.5),
        _bar("10:30:00", 101.5, 104, 101, 103),
    ]

    replay = M.replay_first_hour_confirm(bars)
    partial = M._partial_daily_bar(symbol="AAA", day="2025-01-02", bars=replay.post_entry_bars)

    assert replay.triggered is True
    assert replay.entry_price == 101.5
    assert replay.entry_time == "2025-01-02 10:25:00"
    assert partial is not None
    assert partial.low == 101.0
    assert partial.high == 104.0


def test_first_hour_confirm_rejects_non_confirming_first_hour() -> None:
    bars = [
        _bar("09:30:00", 100, 101, 99, 100.5),
        _bar("10:25:00", 100.5, 101, 98, 99.5),
    ]

    replay = M.replay_first_hour_confirm(bars)

    assert replay.triggered is False
    assert replay.status == "no_entry_trigger"


def test_prior_session_high_breakout_uses_stop_price_and_post_crossing_path() -> None:
    bars = [
        _bar("09:30:00", 100, 101, 98, 100.5),
        _bar("10:00:00", 100.5, 103, 100.2, 102.5),
        _bar("10:05:00", 102.5, 104, 101.5, 103.5),
    ]

    replay = M.replay_prior_session_high_breakout(bars, prior_session_high=102.0)
    partial = M._partial_daily_bar(symbol="AAA", day="2025-01-02", bars=replay.post_entry_bars)

    assert replay.triggered is True
    assert replay.entry_price == 102.0
    assert replay.entry_time == "2025-01-02 10:00:00"
    assert partial is not None
    assert partial.low == 101.5
    assert partial.high == 104.0


def test_gap_above_prior_high_breakout_enters_at_open() -> None:
    bars = [
        _bar("09:30:00", 105, 106, 104, 105.5),
        _bar("09:35:00", 105.5, 107, 105, 106.5),
    ]

    replay = M.replay_prior_session_high_breakout(bars, prior_session_high=102.0)

    assert replay.triggered is True
    assert replay.entry_price == 105.0


def test_pullback_reclaim_waits_for_one_pct_pullback_then_reclaim_close() -> None:
    bars = [
        _bar("09:30:00", 100, 101, 99.5, 100.4),
        _bar("10:00:00", 100.4, 100.8, 98.8, 99.2),
        _bar("10:15:00", 99.2, 101.5, 99.0, 100.7),
        _bar("10:20:00", 100.7, 103.0, 100.5, 102.5),
    ]

    replay = M.replay_pullback_1pct_reclaim(bars)
    partial = M._partial_daily_bar(symbol="AAA", day="2025-01-02", bars=replay.post_entry_bars)

    assert replay.triggered is True
    assert replay.entry_price == 100.7
    assert replay.entry_time == "2025-01-02 10:15:00"
    assert partial is not None
    assert partial.low == 100.5
    assert partial.high == 103.0


def test_entry_assumption_summary_counts_no_entry_as_cash_for_candidate_weighted_return() -> None:
    labels = pd.DataFrame(
        [
            {
                "entry_assumption": "first_hour_confirm",
                "label_triggered": True,
                "label_ret_20d_close_pct": 10.0,
                "label_runner_candidate_20d": True,
                "label_normal_winner_20d": True,
                "label_bad_trade_20d": False,
                "label_t4_s2_20d_outcome": "target_before_stop",
                "label_mfe_20d_pct": 12.0,
                "label_mae_20d_pct": -1.0,
            },
            {
                "entry_assumption": "first_hour_confirm",
                "label_triggered": False,
                "label_ret_20d_close_pct": None,
                "label_runner_candidate_20d": False,
                "label_normal_winner_20d": False,
                "label_bad_trade_20d": False,
                "label_t4_s2_20d_outcome": "unavailable",
                "label_mfe_20d_pct": None,
                "label_mae_20d_pct": None,
            },
        ]
    )

    summary = M.entry_assumption_summary(labels).set_index("entry_assumption")

    assert summary.loc["first_hour_confirm", "avg_ret_20d_close_pct"] == 10.0
    assert summary.loc["first_hour_confirm", "candidate_weighted_avg_ret_20d_pct"] == 5.0
