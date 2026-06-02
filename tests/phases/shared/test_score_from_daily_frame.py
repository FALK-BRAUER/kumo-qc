"""Parity coverage for the score_from_daily_frame extraction (C1 / #276b).

The pure scoring core was extracted out of score_symbol's inline body. These tests prove the
extraction is behavior-preserving: feeding a daily frame straight into score_from_daily_frame
yields the SAME result the score_symbol path produces for the same frame (the only difference
being the LEAN History fetch, which we drive with a fake algorithm here).
"""
from __future__ import annotations

import sys
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

from phases.shared.oracle_helpers import score_from_daily_frame, score_symbol


@pytest.fixture
def stub_quantconnect() -> Any:
    mod = types.ModuleType("QuantConnect")
    resolution = types.SimpleNamespace(DAILY="DAILY", Daily="DAILY")
    mod.Resolution = resolution  # type: ignore[attr-defined]
    sys.modules["QuantConnect"] = mod
    try:
        yield resolution
    finally:
        sys.modules.pop("QuantConnect", None)


class FakeAlgo:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def History(self, symbols: list[Any], bars: int, resolution: Any) -> pd.DataFrame:
        return self._frame.tail(bars)


def _daily_frame(closes: np.ndarray) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _strong_uptrend() -> pd.DataFrame:
    t = np.arange(700, dtype=float)
    closes = 50.0 + 0.25 * t + 2.5 * np.sin(t / 6.0)
    closes[-30:] = closes[-30:] + np.linspace(0.0, 8.0, 30)
    return _daily_frame(closes)


def test_score_from_daily_frame_full_score_on_uptrend() -> None:
    """The pure core scores a strong uptrend 8/8 — the same fixture the inline path scored 8/8."""
    out = score_from_daily_frame(_strong_uptrend())
    assert out is not None
    assert out["score"] == 8
    assert out["rating"] == "+++"
    assert out["conditions"] == [True] * 8


def test_score_from_daily_frame_matches_score_symbol_path(stub_quantconnect: Any) -> None:
    """PARITY: score_symbol (fetch + score) must equal score_from_daily_frame on the same frame."""
    frame = _strong_uptrend()
    via_symbol = score_symbol(FakeAlgo(frame), symbol="AAPL")
    via_pure = score_from_daily_frame(frame)
    assert via_symbol == via_pure


def test_score_from_daily_frame_matches_on_downtrend(stub_quantconnect: Any) -> None:
    """Parity also holds on a bearish frame (different score, identical between paths)."""
    closes = 250.0 - 0.25 * np.arange(700, dtype=float)
    frame = _daily_frame(closes)
    assert score_symbol(FakeAlgo(frame), symbol="X") == score_from_daily_frame(frame)


def test_score_from_daily_frame_none_on_insufficient_history() -> None:
    """Warmup guard preserved: < 230 daily bars -> None."""
    assert score_from_daily_frame(_daily_frame(50.0 + np.arange(100, dtype=float))) is None


def test_score_from_daily_frame_none_on_empty_frame() -> None:
    """Empty frame -> None (len < 230 guard, matching the old _fetch_ohlcv-empty path)."""
    assert score_from_daily_frame(pd.DataFrame()) is None
