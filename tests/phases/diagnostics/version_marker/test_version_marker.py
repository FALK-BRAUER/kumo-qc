"""v2-delta: constructor is VersionMarker(VersionMarker.Params(...), logger=None)."""
from datetime import datetime
from engine.context import PhaseContext
from phases.diagnostics.version_marker.version_marker import VersionMarker


class FakeQC:
    def __init__(self):
        self.logged = []
    def log(self, msg):
        self.logged.append(msg)


def test_version_marker_never_blocks():
    qc = FakeQC()
    phase = VersionMarker(VersionMarker.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    result = phase.evaluate(ctx)
    assert result.blocked is False


def test_version_marker_emits_rebalance_log():
    qc = FakeQC()
    phase = VersionMarker(VersionMarker.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    phase.evaluate(ctx)
    assert any("REBALANCE" in msg for msg in qc.logged)


def test_version_marker_marker():
    phase = VersionMarker(VersionMarker.Params(), logger=None)
    assert phase.version_marker == "version_marker_v1"
