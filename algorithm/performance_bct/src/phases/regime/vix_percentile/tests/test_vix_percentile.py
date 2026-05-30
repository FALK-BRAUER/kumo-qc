from datetime import datetime
from engine.context import PhaseContext
from phases.regime.vix_percentile.vix_percentile import VixPercentile


def make_ctx(qc=None):
    class EmptyQC:
        vix = None
        securities = {}
    return PhaseContext(qc=qc or EmptyQC(), time=datetime(2025, 1, 2), data=None)


def test_disabled_by_default_passes():
    phase = VixPercentile(params={}, logger=None)
    result = phase.evaluate(make_ctx())
    assert result.blocked is False
    assert result.decision == "skip"


def test_disabled_explicitly_passes():
    phase = VixPercentile(params={"vix_percentile_enabled": False}, logger=None)
    result = phase.evaluate(make_ctx())
    assert result.blocked is False


def test_enabled_with_no_vix_passes():
    phase = VixPercentile(params={"vix_percentile_enabled": True}, logger=None)
    result = phase.evaluate(make_ctx())
    assert result.blocked is False  # no VIX → safe fallback
