"""Tests for runtime.universe_select rolling-20d-DV maintenance (incremental-DV / scaling fix).

The incremental-DV design replaces the per-day history() fan-out with a MAINTAINED rolling
20-day dollar-volume per coarse name, pushed once per day from the COARSE feed's single-day DV.
The pure core is GOLDEN-MASTERED: the rolling-20d mean over a stream of daily DV inputs MUST
equal mean(inputs[-20:]) on identical inputs — the algorithm preserves the OLD path's
trailing-mean semantics exactly (only the SOURCE of the per-day DV changes: coarse single-day
DV instead of RAW history close*volume; GATE 1 proved these are equal/split-invariant).

Covered: cold start (<20 days -> partial-window mean), full window, drop-oldest behavior,
a name with a gap day, and the maintenance+eviction control-flow (update_dv_windows).
"""
from __future__ import annotations

from collections import deque

from runtime.universe_select import (
    ADV_WINDOW,
    DvWindow,
    rolling_dv_mean,
    update_dv_windows,
)


# --------------------------------------------------------------------------------------
# Inline independent reference: the trailing-mean over the last `maxlen` inputs. Written
# differently from the impl (slice + sum/len, not a maintained deque) so a shared bug can't hide.
# --------------------------------------------------------------------------------------
def _ref_trailing_mean(inputs, maxlen):
    tail = inputs[-maxlen:]
    return sum(tail) / len(tail) if tail else 0.0


def _feed_window(inputs, maxlen=ADV_WINDOW):
    """Push a stream of daily DV inputs through a maxlen deque, return its current mean."""
    w: deque[float] = deque(maxlen=maxlen)
    for x in inputs:
        w.append(x)
    return rolling_dv_mean(w)


# ---- rolling_dv_mean golden master ----
def test_rolling_dv_mean_cold_start_partial_window():
    # <20 days: mean over the partial window == mean of all inputs so far.
    inputs = [1.0e8, 2.0e8, 3.0e8]
    assert _feed_window(inputs) == _ref_trailing_mean(inputs, ADV_WINDOW)
    assert _feed_window(inputs) == 2.0e8


def test_rolling_dv_mean_full_window_exactly_20():
    inputs = [float(i) * 1.0e7 for i in range(1, 21)]  # 20 values
    assert _feed_window(inputs) == _ref_trailing_mean(inputs, ADV_WINDOW)


def test_rolling_dv_mean_drops_oldest_beyond_20():
    # 25 inputs: only the last 20 survive; mean must equal mean(inputs[-20:]).
    inputs = [float(i) * 1.0e7 for i in range(1, 26)]  # 25 values
    got = _feed_window(inputs)
    assert got == _ref_trailing_mean(inputs, ADV_WINDOW)
    # explicit: drop-oldest means the first 5 (1e7..5e7) are gone.
    assert got == sum(inputs[5:]) / 20


def test_rolling_dv_mean_golden_master_over_long_stream():
    # A 200-day stream of varied DV: at every step the maintained mean == reference tail mean.
    import random
    rng = random.Random(42)
    stream = [rng.uniform(5e7, 5e9) for _ in range(200)]
    w: deque[float] = deque(maxlen=ADV_WINDOW)
    for i, x in enumerate(stream):
        w.append(x)
        assert abs(rolling_dv_mean(w) - _ref_trailing_mean(stream[: i + 1], ADV_WINDOW)) < 1e-6


def test_rolling_dv_mean_empty_window_is_zero():
    assert rolling_dv_mean(deque(maxlen=ADV_WINDOW)) == 0.0


def test_adv_window_default_is_20():
    assert ADV_WINDOW == 20


# ---- update_dv_windows maintenance + eviction control-flow ----
def test_update_dv_windows_pushes_todays_dv():
    windows: dict[str, DvWindow] = {}
    update_dv_windows(windows, {"aaa": 1.0e8, "bbb": 2.0e8}, day_index=0)
    assert set(windows) == {"aaa", "bbb"}
    assert rolling_dv_mean(windows["aaa"].dv) == 1.0e8
    assert rolling_dv_mean(windows["bbb"].dv) == 2.0e8


def test_update_dv_windows_accumulates_across_days():
    windows: dict[str, DvWindow] = {}
    for day, dv in enumerate([1.0e8, 3.0e8]):  # two days for aaa
        update_dv_windows(windows, {"aaa": dv}, day_index=day)
    assert rolling_dv_mean(windows["aaa"].dv) == 2.0e8  # mean(1e8, 3e8)


def test_update_dv_windows_gap_day_does_not_update_absent_name():
    # 'aaa' present day0, ABSENT day1, present day2 -> its window has only the two days it
    # appeared (a 1-day gap must NOT inject a zero / must NOT evict on a single absence).
    windows: dict[str, DvWindow] = {}
    update_dv_windows(windows, {"aaa": 1.0e8, "bbb": 9.0e8}, day_index=0)
    update_dv_windows(windows, {"bbb": 9.0e8}, day_index=1)  # aaa absent this day
    update_dv_windows(windows, {"aaa": 3.0e8, "bbb": 9.0e8}, day_index=2)
    # aaa survived the 1-day gap; window = [1e8, 3e8] (the absent day injected nothing).
    assert "aaa" in windows
    assert list(windows["aaa"].dv) == [1.0e8, 3.0e8]
    assert rolling_dv_mean(windows["aaa"].dv) == 2.0e8


def test_update_dv_windows_evicts_long_absent_names():
    # A name absent for >= ADV_WINDOW consecutive days is stale (its window would have fully
    # aged out anyway) -> evicted to bound memory.
    windows: dict[str, DvWindow] = {}
    update_dv_windows(windows, {"gone": 1.0e8, "live": 2.0e8}, day_index=0)
    # advance ADV_WINDOW more days with 'gone' absent every day
    for day in range(1, ADV_WINDOW + 1):
        update_dv_windows(windows, {"live": 2.0e8}, day_index=day)
    assert "gone" not in windows  # evicted after ADV_WINDOW-day absence
    assert "live" in windows


def test_update_dv_windows_caps_window_at_adv_window():
    windows: dict[str, DvWindow] = {}
    for day in range(30):  # 30 days of the same name
        update_dv_windows(windows, {"aaa": float(day + 1) * 1.0e7}, day_index=day)
    # window holds at most ADV_WINDOW entries (drop-oldest).
    assert len(windows["aaa"].dv) == ADV_WINDOW
    assert list(windows["aaa"].dv) == [float(d + 1) * 1.0e7 for d in range(10, 30)]
