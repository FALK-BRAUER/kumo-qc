"""Behavioral contract (#245) for the VIX-percentile regime gate.

v2-delta: constructor is VixPercentile(VixPercentile.Params(...), logger=None).

The phase early-returns `skip` when disabled / no VIX. The REAL decision is the
enabled compute path (src ~:50-71): it pulls `lookback` bars of VIX history via
`qc.history(...)`, computes the percentile of the live price within that window
(`vix_pct = (series < vix_now).mean()*100`) and sets `blocked = vix_pct > threshold`.

To exercise that path the phase does `from QuantConnect import Resolution` and
`import pandas as pd` inside `evaluate`. QuantConnect is not importable in the dev
venv, so we inject a minimal stub into sys.modules (fixture) exposing
`Resolution.DAILY`; pandas IS installed. The FakeQC then supplies a real pandas
DataFrame history + a live price so the compute runs verbatim (no skip).
"""
from __future__ import annotations

import sys
import types
from datetime import datetime

import pandas as pd
import pytest

from engine.context import PhaseContext
from phases.regime.vix_percentile.vix_percentile import VixPercentile


# ---------------------------------------------------------------------------
# QuantConnect stub — the phase does `from QuantConnect import Resolution`.
# Without this the import raises ModuleNotFoundError, the bare `except Exception`
# swallows it, and the compute path never runs (returns "VIX percentile error").
# ---------------------------------------------------------------------------
@pytest.fixture()
def quantconnect_stub():
    mod = types.ModuleType("QuantConnect")
    resolution = types.SimpleNamespace(DAILY="Daily")
    mod.Resolution = resolution  # type: ignore[attr-defined]
    sys.modules["QuantConnect"] = mod
    try:
        yield
    finally:
        sys.modules.pop("QuantConnect", None)


# ---------------------------------------------------------------------------
# FakeQC that drives the enabled compute path.
# ---------------------------------------------------------------------------
class FakeSecurity:
    def __init__(self, price: float) -> None:
        self.price = price


class FakeSecurities(dict):
    def contains_key(self, key) -> bool:  # type: ignore[no-untyped-def]
        return key in self


class FakeQC:
    """Supplies exactly what vix_percentile.evaluate() reads on the compute path:
    qc.vix, qc.securities.contains_key(vix), qc.history(...) -> DataFrame, qc.securities[vix].price.
    """

    def __init__(self, vix_closes, vix_now, multiindex=False):
        self.vix = "VIX"
        self.securities = FakeSecurities()
        self.securities[self.vix] = FakeSecurity(vix_now)
        self._vix_closes = vix_closes
        self._multiindex = multiindex

    def history(self, symbol, lookback, resolution):  # type: ignore[no-untyped-def]
        # Return a DataFrame with a lowercase "close" column, like LEAN's history().
        df = pd.DataFrame({"close": self._vix_closes})
        if self._multiindex:
            idx = pd.MultiIndex.from_tuples([(symbol, i) for i in range(len(self._vix_closes))])
            df.index = idx
        return df


def make_ctx(qc=None):
    class EmptyQC:
        vix = None
        securities = {}
    return PhaseContext(qc=qc or EmptyQC(), time=datetime(2025, 1, 2), data=None)


# ---------------------------------------------------------------------------
# Early-return / disabled paths (kept — these are the legitimate skip branches).
# ---------------------------------------------------------------------------
def test_disabled_by_default_passes():
    phase = VixPercentile(VixPercentile.Params(), logger=None)
    result = phase.evaluate(make_ctx())
    assert result.blocked is False
    assert result.decision == "skip"


def test_disabled_explicitly_passes():
    phase = VixPercentile(VixPercentile.Params(vix_percentile_enabled=False), logger=None)
    result = phase.evaluate(make_ctx())
    assert result.blocked is False


def test_enabled_with_no_vix_passes():
    phase = VixPercentile(VixPercentile.Params(vix_percentile_enabled=True), logger=None)
    result = phase.evaluate(make_ctx())
    assert result.blocked is False  # no VIX → safe fallback
    assert result.decision == "skip"


# ---------------------------------------------------------------------------
# FIRE — enabled, VIX above threshold → blocked=True (the gate engages).
# ---------------------------------------------------------------------------
def test_enabled_vix_above_threshold_blocks(quantconnect_stub):
    # Distribution 1..100; live price 96 → 95/100 of the window are below it →
    # vix_pct = 95.0 > threshold 75 → blocked.
    lookback = 100
    closes = [float(i) for i in range(1, lookback + 1)]
    qc = FakeQC(vix_closes=closes, vix_now=96.0)
    phase = VixPercentile(
        VixPercentile.Params(
            vix_percentile_enabled=True,
            vix_percentile_threshold=75.0,
            vix_percentile_lookback=lookback,
        ),
        logger=None,
    )
    result = phase.evaluate(make_ctx(qc))

    assert result.decision == "block"
    assert bool(result.blocked) is True  # numpy bool from `vix_pct > threshold`
    assert result.facts["pct"] == pytest.approx(95.0)
    assert result.facts["vix"] == pytest.approx(96.0)
    assert result.facts["threshold"] == 75.0


# ---------------------------------------------------------------------------
# DECLINE — enabled, VIX below threshold → blocked=False (gate passes).
# ---------------------------------------------------------------------------
def test_enabled_vix_below_threshold_passes(quantconnect_stub):
    # Live price 21 → 20/100 below it → vix_pct = 20.0 < threshold 75 → pass.
    lookback = 100
    closes = [float(i) for i in range(1, lookback + 1)]
    qc = FakeQC(vix_closes=closes, vix_now=21.0)
    phase = VixPercentile(
        VixPercentile.Params(
            vix_percentile_enabled=True,
            vix_percentile_threshold=75.0,
            vix_percentile_lookback=lookback,
        ),
        logger=None,
    )
    result = phase.evaluate(make_ctx(qc))

    assert result.decision == "pass"
    assert bool(result.blocked) is False
    assert result.facts["pct"] == pytest.approx(20.0)


def test_enabled_handles_multiindex_history(quantconnect_stub):
    # LEAN often returns a MultiIndex (symbol, time); the phase droplevel(0)s it.
    # Drive the same above-threshold decision through the MultiIndex branch.
    lookback = 100
    closes = [float(i) for i in range(1, lookback + 1)]
    qc = FakeQC(vix_closes=closes, vix_now=96.0, multiindex=True)
    phase = VixPercentile(
        VixPercentile.Params(
            vix_percentile_enabled=True,
            vix_percentile_threshold=75.0,
            vix_percentile_lookback=lookback,
        ),
        logger=None,
    )
    result = phase.evaluate(make_ctx(qc))
    assert bool(result.blocked) is True
    assert result.decision == "block"


# ---------------------------------------------------------------------------
# Edge — enabled but history too short (< 80% of lookback) → skip, not crash.
# ---------------------------------------------------------------------------
def test_enabled_insufficient_history_skips(quantconnect_stub):
    lookback = 100
    closes = [float(i) for i in range(50)]  # 50 < 0.8*100 → insufficient
    qc = FakeQC(vix_closes=closes, vix_now=50.0)
    phase = VixPercentile(
        VixPercentile.Params(
            vix_percentile_enabled=True,
            vix_percentile_threshold=75.0,
            vix_percentile_lookback=lookback,
        ),
        logger=None,
    )
    result = phase.evaluate(make_ctx(qc))
    assert result.decision == "skip"
    assert result.blocked is False
    assert "insufficient VIX history" in result.reason


def test_enabled_boundary_pct_equals_threshold_does_not_block(quantconnect_stub):
    # `blocked = vix_pct > threshold` is strict-greater. At pct == threshold → NOT blocked.
    lookback = 100
    closes = [float(i) for i in range(1, lookback + 1)]
    # live price 76 → 75/100 below → pct = 75.0 == threshold 75.0 → NOT blocked (strict >).
    qc = FakeQC(vix_closes=closes, vix_now=76.0)
    phase = VixPercentile(
        VixPercentile.Params(
            vix_percentile_enabled=True,
            vix_percentile_threshold=75.0,
            vix_percentile_lookback=lookback,
        ),
        logger=None,
    )
    result = phase.evaluate(make_ctx(qc))
    assert result.facts["pct"] == pytest.approx(75.0)
    assert bool(result.blocked) is False
    assert result.decision == "pass"
