from __future__ import annotations

from scripts import build_scanner_opportunity_path_labels as M


def _bar(day: str, open_: float, high: float, low: float, close: float) -> M.DailyBar:
    return M.DailyBar(symbol="AAA", day=day, open=open_, high=high, low=low, close=close, volume=1000)


def test_target_stop_outcome_orders_by_daily_bars() -> None:
    bars = [
        _bar("2025-01-02", 100, 103, 99, 101),
        _bar("2025-01-03", 101, 105, 100, 104),
    ]

    assert (
        M.target_stop_outcome(entry_price=100, bars=bars, target_pct=4, stop_pct=2)
        == "target_before_stop"
    )


def test_stop_before_target_and_ambiguous_same_day() -> None:
    stop_first = [
        _bar("2025-01-02", 100, 101, 97, 98),
        _bar("2025-01-03", 98, 105, 98, 104),
    ]
    ambiguous = [_bar("2025-01-02", 100, 105, 97, 101)]

    assert (
        M.target_stop_outcome(entry_price=100, bars=stop_first, target_pct=4, stop_pct=2)
        == "stop_before_target"
    )
    assert (
        M.target_stop_outcome(entry_price=100, bars=ambiguous, target_pct=4, stop_pct=2)
        == "ambiguous_same_day"
    )


def test_horizon_metrics_compute_mfe_mae_time_to_peak_and_giveback() -> None:
    scheduled = ["2025-01-02", "2025-01-03", "2025-01-06"]
    bars = {
        "2025-01-02": _bar("2025-01-02", 100, 103, 99, 102),
        "2025-01-03": _bar("2025-01-03", 102, 110, 101, 108),
        "2025-01-06": _bar("2025-01-06", 108, 109, 104, 105),
    }

    metrics = M.horizon_metrics(entry_price=100, scheduled_days=scheduled, bars_by_day=bars, horizon=3)

    assert metrics["label_ret_3d_close_pct"] == 5.0
    assert metrics["label_mfe_3d_pct"] == 10.0
    assert metrics["label_mae_3d_pct"] == -1.0
    assert metrics["label_time_to_peak_3d_sessions"] == 2
    assert metrics["label_max_giveback_after_peak_3d_pct"] == 9.0


def test_labels_for_opportunity_marks_missing_entry_and_truncated_calendar() -> None:
    calendar = ["2025-01-02", "2025-01-03"]
    missing = M.labels_for_opportunity(
        {"scan_date": "2025-01-01", "symbol": "AAA"},
        calendar=calendar,
        bars={},
        horizons=(1, 2, 5),
    )
    assert missing["label_path_status"] == "missing_entry_bar"
    assert missing["label_outcome_20d"] == "unavailable"

    bars = {
        ("AAA", "2025-01-02"): _bar("2025-01-02", 100, 104, 99, 103),
        ("AAA", "2025-01-03"): _bar("2025-01-03", 103, 105, 101, 104),
    }
    truncated = M.labels_for_opportunity(
        {"scan_date": "2025-01-01", "symbol": "AAA"},
        calendar=calendar,
        bars=bars,
        horizons=(1, 2, 5),
    )

    assert truncated["label_path_status"] == "truncated_calendar"
    assert truncated["label_available_5d_sessions"] == 2
    assert truncated["label_t4_s2_2d_outcome"] == "target_before_stop"


def test_compact_outcome_prioritizes_stop_first_bad_trade() -> None:
    row = {
        "label_path_status": "available_full_40d",
        "label_mfe_20d_pct": 40.0,
        "label_mae_20d_pct": -12.0,
        "label_ret_20d_close_pct": -8.0,
        "label_t4_s2_20d_outcome": "stop_before_target",
    }

    M.add_compact_labels(row)

    assert row["label_runner_candidate_20d"] is True
    assert row["label_bad_trade_20d"] is True
    assert row["label_outcome_20d"] == "bad_trade"
