"""MarketBreadthGate: breadth>threshold passes, <=threshold blocks, cold default blocks."""
from datetime import datetime
from engine.context import PhaseContext
from phases.regime.market_breadth_gate.market_breadth_gate import MarketBreadthGate


class _QC:
    def __init__(self, breadth):
        if breadth is not None:
            self.breadth_pct_above_200ma = breadth


def _ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)


def _run(breadth, threshold=0.50, missing_breadth_blocks=True):
    p = MarketBreadthGate(
        MarketBreadthGate.Params(
            pct_threshold=threshold,
            missing_breadth_blocks=missing_breadth_blocks,
        ),
        logger=None,
    )
    return p.evaluate(_ctx(_QC(breadth)))


def test_breadth_above_threshold_passes():
    r = _run(0.62, 0.50)
    assert r.blocked is False and r.decision == "pass"


def test_breadth_at_or_below_threshold_blocks():
    assert _run(0.50, 0.50).blocked is True   # boundary: <= blocks
    assert _run(0.30, 0.50).blocked is True


def test_cold_breadth_fail_closed_blocks():
    assert _run(None).blocked is True          # missing → BLOCK (never fail-open)


def test_fixture_can_skip_cold_breadth_without_blocking():
    r = _run(None, missing_breadth_blocks=False)
    assert r.blocked is False
    assert r.decision == "skip"


def test_param_threshold_40_for_scenario_c():
    assert _run(0.45, 0.40).blocked is False   # 45% > 40% (C) passes
    assert _run(0.45, 0.50).blocked is True    # 45% <= 50% (A) blocks
