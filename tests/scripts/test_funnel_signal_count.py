"""Coverage for the C1 signal-count harness (scripts/funnel_signal_count.py).

The load-from-LEAN-zip path needs real data, so the harness is exercised end-to-end in the
manual run. Here we lock the two things that MUST be correct for the verdict to be trustworthy:
  1. as-of slicing has NO look-ahead (never returns a bar dated after the decision date),
  2. the score histogram / count-at-least helpers aggregate correctly.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from funnel_signal_count import _count_at_least, sample_dates, slice_as_of  # noqa: E402


def _frame(n: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = 100.0 + np.arange(n, dtype=float)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1.0},
        index=idx,
    )


def test_slice_as_of_no_lookahead() -> None:
    """No returned bar may be dated after the as-of decision date."""
    df = _frame(400)
    as_of = df.index[250]
    sliced = slice_as_of(df, as_of, bars=700)
    assert len(sliced) == 251  # bars 0..250 inclusive
    assert sliced.index.max() == as_of
    assert (sliced.index <= as_of).all()


def test_slice_as_of_caps_bar_count() -> None:
    """Keeps only the last `bars` bars up to the as-of date."""
    df = _frame(900)
    as_of = df.index[-1]
    sliced = slice_as_of(df, as_of, bars=700)
    assert len(sliced) == 700
    assert sliced.index.max() == as_of
    # the kept window is the most-recent 700, so the earliest kept bar is index[200]
    assert sliced.index.min() == df.index[200]


def test_slice_as_of_excludes_future_when_asof_between_bars() -> None:
    """An as-of timestamp strictly between two bars still excludes the later bar."""
    df = _frame(10)
    as_of = df.index[4] + pd.Timedelta(hours=12)  # after bar 4, before bar 5
    sliced = slice_as_of(df, as_of, bars=700)
    assert sliced.index.max() == df.index[4]
    assert len(sliced) == 5


def test_count_at_least() -> None:
    hist = {4: 10, 5: 8, 6: 5, 7: 3, 8: 2}
    assert _count_at_least(hist, 7) == 5  # 3 + 2
    assert _count_at_least(hist, 6) == 10  # 5 + 3 + 2
    assert _count_at_least(hist, 8) == 2
    assert _count_at_least(hist, 9) == 0


def test_sample_dates_spreads_and_dedupes() -> None:
    dates = [f"2025-{m:02d}-01" for m in range(1, 13)]  # 12 dates
    picked = sample_dates(dates, 4)
    assert picked[0] == dates[0]
    assert picked[-1] == dates[-1]
    assert picked == sorted(picked)
    assert len(picked) == len(set(picked))


def test_sample_dates_returns_all_when_n_exceeds() -> None:
    dates = ["2025-01-01", "2025-02-01"]
    assert sample_dates(dates, 10) == dates
