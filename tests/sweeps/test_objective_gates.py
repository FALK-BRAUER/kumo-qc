"""Gate tests (#323 B.4) — trade-count gate, window weighting, event-windows, and the
W5-concentration robustness guard (the single-window-carried rejection).

Synthetic window/trade fixtures only — ZERO backtest.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from sweeps.objective.gates import (
    MAX_SINGLE_WINDOW_SHARE,
    WindowReturns,
    concentration_guard,
    event_windows,
    trade_count_gate,
    window_weight,
)
from sweeps.types import TradeRecord, Window


def _w(name: str) -> Window:
    return Window(name=name, start="2025-01-01", end="2025-02-28")


def _panel(rets: list[float], trades: list[int], oos_idx: int | None = None) -> list[WindowReturns]:
    out = []
    for i, (r, t) in enumerate(zip(rets, trades)):
        out.append(WindowReturns(_w(f"w{i}"), t, r, is_oos=(i == oos_idx)))
    return out


# --- window_weight --- #
def test_window_weight_caps_at_one_and_scales_below_target() -> None:
    assert window_weight(30) == pytest.approx(1.0)
    assert window_weight(45) == pytest.approx(1.0)  # caps at 1
    assert window_weight(15) == pytest.approx(0.5)
    assert window_weight(0) == pytest.approx(0.0)


def test_window_weight_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        window_weight(10, t_target=0)
    with pytest.raises(ValueError):
        window_weight(-1)


# --- trade_count_gate --- #
def test_trade_count_gate_passes_a_well_traded_panel() -> None:
    panel = _panel([0.05] * 6, [15] * 6)
    assert trade_count_gate(panel).passed


def test_trade_count_gate_rejects_below_total_floor() -> None:
    panel = _panel([0.05] * 6, [3] * 6)  # 18 < 50
    v = trade_count_gate(panel)
    assert not v.passed and "total trades" in v.reason


def test_trade_count_gate_rejects_too_few_well_traded_windows() -> None:
    # total 60 (>=50) but only 3 of 6 windows have >=10 trades (need >3).
    panel = _panel([0.05] * 6, [20, 20, 20, 0, 0, 0])
    v = trade_count_gate(panel)
    assert not v.passed and ">=10 trades" in v.reason


def test_trade_count_gate_excludes_stress_window_from_the_count() -> None:
    panel = _panel([0.05] * 6, [10] * 6)
    panel.append(WindowReturns(_w("fy_stress"), 5, 0.0, is_stress=True))
    assert trade_count_gate(panel).passed  # stress not counted against the gate


# --- concentration_guard (the W5 guard) --- #
def test_concentration_guard_passes_a_broadly_positive_panel() -> None:
    panel = _panel([0.04, 0.05, 0.03, 0.06, 0.04, 0.05], [15] * 6, oos_idx=5)
    assert concentration_guard(panel).passed


def test_concentration_guard_rejects_single_window_carried_config() -> None:
    # W5 supplies ~all positive return; the rest are flat -> single-window-carried.
    panel = _panel([0.001, 0.001, 0.001, 0.001, 0.001, 0.30], [12] * 6)
    v = concentration_guard(panel)
    assert not v.passed
    assert "single-window-carried" in v.reason
    assert "w5" in v.reason


def test_concentration_guard_share_threshold_is_the_boundary() -> None:
    # One window just over MAX_SINGLE_WINDOW_SHARE of the positive total -> reject.
    # total positive = 100; top = 70 -> 70% > 60%.
    panel = _panel([0.70, 0.10, 0.10, 0.10, 0.0, 0.0], [12] * 6)
    v = concentration_guard(panel)
    assert not v.passed
    assert f"{int(MAX_SINGLE_WINDOW_SHARE * 100)}%" in v.reason


def test_concentration_guard_rejects_negative_oos() -> None:
    panel = _panel([0.05, 0.05, 0.05, 0.05, 0.05, -0.02], [15] * 6, oos_idx=5)
    v = concentration_guard(panel)
    assert not v.passed and "OOS" in v.reason


def test_concentration_guard_rejects_more_than_one_negative_window() -> None:
    panel = _panel([0.05, -0.03, 0.05, -0.04, 0.05, 0.05], [15] * 6)
    v = concentration_guard(panel)
    assert not v.passed and "negative windows" in v.reason


def test_concentration_guard_tolerates_exactly_one_negative_window() -> None:
    # all-but-one positive, no single-window dominance, OOS positive -> robust enough.
    panel = _panel([0.05, -0.01, 0.05, 0.05, 0.05, 0.05], [15] * 6, oos_idx=5)
    assert concentration_guard(panel).passed


# --- event_windows --- #
def test_event_windows_slices_into_target_sized_spans() -> None:
    trades = [
        TradeRecord("AAPL", datetime(2025, 1, 1 + i % 28), datetime(2025, 1, 2 + i % 27), 1.0, 0.01)
        for i in range(65)
    ]
    ew = event_windows(trades, trades_per_window=30)
    # 65 trades @30 -> two full spans (30 + 35-merged-remainder), not three.
    assert len(ew) == 2


def test_event_windows_empty_trades_yields_no_windows() -> None:
    assert event_windows([], trades_per_window=30) == []


def test_event_windows_single_short_span_stands_alone() -> None:
    trades = [
        TradeRecord("X", datetime(2025, 1, 1), datetime(2025, 1, 2), 1.0, 0.01) for _ in range(10)
    ]
    ew = event_windows(trades, trades_per_window=30)
    assert len(ew) == 1
