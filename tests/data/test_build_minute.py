"""#275 — the 5-min-as-minute builder: format conformance + the FAIL-LOUD spacing guard.

Option C (HQ-approved): our Massive feed is natively 5-min (78 RTH bars/day = George's BCT cadence);
we store it as LEAN minute-resolution zips and consume it directly (no consolidator). The builder
MUST (1) write the exact LEAN minute format, (2) RAISE on mis-spaced (true-1-min/irregular) data so
a mislabel can't silently corrupt the 5-min intraday indicators (#261 fail-loud class).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "build_minute",
    str(Path(__file__).resolve().parents[2] / "scripts" / "build_minute_from_parquet.py"),
)
assert _spec and _spec.loader
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)


def _times(start: str, n: int, minutes: int) -> list[pd.Timestamp]:
    t0 = pd.Timestamp(start)
    return [t0 + pd.Timedelta(minutes=minutes * i) for i in range(n)]


# ── format ──

def test_ms_of_day_matches_lean() -> None:
    # 09:30 RTH open → 34200000 ms (the LEAN minute timestamp = bar START, ms-since-midnight).
    assert bm.ms_of_day(pd.Timestamp("2025-01-02 09:30:00")) == 34_200_000
    assert bm.ms_of_day(pd.Timestamp("2025-01-02 15:55:00")) == 57_300_000


def test_price_to_deci_cents() -> None:
    assert bm.pi(124.13) == 1_241_300  # x10000, the LEAN deci-cent scale
    assert bm.pi(0.0) == 0


def test_lean_name_lowercases_and_dots() -> None:
    assert bm.lean_name("BRK-B") == "brk.b"
    assert bm.lean_name("AAPL") == "aapl"


# ── the FAIL-LOUD spacing guard (#275 requirement 2 / #261 class) ──

def test_spacing_guard_raises_on_true_1min() -> None:
    # a true-1-min feed (the mislabel we must catch) → SpacingError in strict mode.
    with pytest.raises(bm.SpacingError, match="NOT 5-min"):
        bm._check_spacing("AAPL", "20250102", _times("2025-01-02 09:30:00", 30, 1), strict=True)


def test_spacing_guard_passes_on_5min() -> None:
    # the correct cadence → passes.
    assert bm._check_spacing("AAPL", "20250102", _times("2025-01-02 09:30:00", 78, 5), strict=True)


def test_spacing_guard_tolerates_a_few_gaps() -> None:
    # a handful of missing bars (halts) must NOT trip the guard — only systematic mis-spacing.
    t = _times("2025-01-02 09:30:00", 40, 5)
    del t[10]; del t[20]  # two gaps → one 600s delta each; well under the >max(3,10%) threshold
    assert bm._check_spacing("AAPL", "20250102", t, strict=True)


def test_spacing_guard_report_mode_skips_not_raises() -> None:
    # --report mode: a mis-spaced day is skipped (returns False), not raised — for a bulk audit.
    assert bm._check_spacing("AAPL", "20250102", _times("2025-01-02 09:30:00", 30, 1), strict=False) is False


def test_single_bar_day_not_flagged() -> None:
    # a 1-bar day can't be mis-spaced (no delta to check) → passes.
    assert bm._check_spacing("AAPL", "20250102", _times("2025-01-02 09:30:00", 1, 5), strict=True)


def test_spacing_guard_threshold_boundary() -> None:
    # The tolerance threshold is > max(3, len(deltas)//10). Pin it on a full-ish day so the
    # boundary can't drift silently: 78 bars → 77 deltas → floor max(3,7)=7. Build a monotonic
    # series with EXACTLY n_bad 1-min deltas (the rest 5-min): n_bad=7 PASSES (not > 7), 8 RAISES.
    def day_with_bad(n_bad: int) -> list[pd.Timestamp]:
        t = [pd.Timestamp("2025-01-02 09:30:00")]
        for i in range(77):  # 77 deltas → 78 bars
            step = 1 if i < n_bad else 5  # first n_bad deltas = 1-min (bad), rest 5-min
            t.append(t[-1] + pd.Timedelta(minutes=step))
        return t
    # exactly 7 bad deltas = at the floor (7 is not > 7) → passes
    assert bm._check_spacing("AAPL", "20250102", day_with_bad(7), strict=True)
    # 8 bad deltas > floor → raises
    with pytest.raises(bm.SpacingError):
        bm._check_spacing("AAPL", "20250102", day_with_bad(8), strict=True)
