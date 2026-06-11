from __future__ import annotations

from scripts import analyze_scanner_exit_policies as M
from scripts import build_scanner_opportunity_path_labels as labels


def _bar(day: str, open_: float, high: float, low: float, close: float) -> labels.DailyBar:
    return labels.DailyBar(symbol="AAA", day=day, open=open_, high=high, low=low, close=close, volume=1000)


def test_fixed_target_stop_uses_conservative_stop_first_on_ambiguous_day() -> None:
    result = M.simulate_fixed_target_stop(
        policy_id="fixed_t4_s2",
        entry_price=100,
        bars=[_bar("2025-01-02", 100, 105, 97, 101)],
        target_pct=4,
        stop_pct=2,
    )

    assert result.policy_status == "closed"
    assert result.exit_reason == "ambiguous_stop_first"
    assert result.total_equity_ret_40d_pct == -2.0
    assert result.ambiguous_same_day is True


def test_partial_target_trail_realizes_half_and_keeps_remainder_open() -> None:
    result = M.simulate_partial_target_trail(
        entry_price=100,
        bars=[
            _bar("2025-01-02", 100, 105, 99, 104),
            _bar("2025-01-03", 104, 111, 103, 110),
        ],
    )

    assert result.policy_status == "open_at_horizon"
    assert result.partial_taken is True
    assert result.realized_ret_pct == 2.0
    assert result.open_fraction_40d == 0.5
    assert result.open_mtm_ret_40d_pct == 5.0
    assert result.total_equity_ret_40d_pct == 7.0


def test_giveback_after_peak_exits_after_prior_peak_is_armed() -> None:
    result = M.simulate_giveback_after_peak(
        entry_price=100,
        bars=[
            _bar("2025-01-02", 100, 110, 99, 109),
            _bar("2025-01-03", 109, 111, 105, 106),
        ],
    )

    assert result.policy_status == "closed"
    assert result.exit_reason == "giveback_stop"
    assert result.exit_session == 2
    assert result.total_equity_ret_40d_pct == 6.5


def test_time_stop_exits_on_session_10_when_return_below_threshold() -> None:
    bars = [_bar(f"2025-01-{day:02d}", 100, 102, 98, 101) for day in range(2, 12)]

    result = M.simulate_time_stop(entry_price=100, bars=bars)

    assert result.policy_status == "closed"
    assert result.exit_reason == "time_stop_under_threshold"
    assert result.exit_session == 10
    assert result.total_equity_ret_40d_pct == 1.0


def test_sector_weakness_exits_when_etf_three_day_return_breaks_threshold() -> None:
    stock = [
        _bar("2025-01-02", 100, 102, 99, 101),
        _bar("2025-01-03", 101, 103, 100, 102),
        _bar("2025-01-06", 102, 104, 101, 103),
        _bar("2025-01-07", 103, 105, 102, 104),
    ]
    etf = [
        labels.DailyBar("XLF", "2025-01-02", 100, 100, 100, 100, 1000),
        labels.DailyBar("XLF", "2025-01-03", 100, 100, 99, 99, 1000),
        labels.DailyBar("XLF", "2025-01-06", 99, 99, 98, 98, 1000),
        labels.DailyBar("XLF", "2025-01-07", 98, 98, 96, 96, 1000),
    ]

    result = M.simulate_sector_weakness(entry_price=100, bars=stock, etf_bars=etf)

    assert result.policy_status == "closed"
    assert result.exit_reason == "sector_etf_3d_weakness"
    assert result.exit_session == 4
    assert result.total_equity_ret_40d_pct == 4.0
