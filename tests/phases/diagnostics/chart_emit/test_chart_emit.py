"""chart_emit phase tests (#243).

Constructor mirrors the diagnostics convention: ChartEmit(ChartEmit.Params(...), logger).
FakeQC captures plot() calls as (chart, series, value) tuples. A FakeQC WITHOUT a plot
attribute must no-op gracefully (no AttributeError) — the getattr-guard for test fakes.
"""
from datetime import datetime

from engine.context import BarState, PhaseContext
from phases.diagnostics.chart_emit.chart_emit import ChartEmit


class FakeQC:
    """Captures plot() calls; optionally carries _ranked_today."""

    def __init__(self, ranked_today=None, has_ranked_attr=True):
        self.plots: list[tuple[str, str, float]] = []
        if has_ranked_attr:
            self._ranked_today = ranked_today if ranked_today is not None else []

    def plot(self, chart, series, value):
        self.plots.append((chart, series, value))


class FakeQCNoPlot:
    """A QC fake that lacks a plot attribute entirely (graceful no-op path)."""

    def __init__(self, ranked_today=None):
        self._ranked_today = ranked_today if ranked_today is not None else []


def _ctx(qc, ranked_candidates=None):
    bs = BarState(ranked_candidates=list(ranked_candidates or []))
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None, bar_state=bs)


def test_metadata():
    assert ChartEmit.PHASE_KIND == "diagnostics"
    assert ChartEmit.REQUIRES_UPSTREAM == []
    assert ChartEmit.PROVIDES_DOWNSTREAM == []


def test_version_marker():
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    assert phase.version_marker == "chart_emit_v1"


def test_never_blocks():
    qc = FakeQC(ranked_today=["AAPL"])
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc, ["AAPL"]))
    assert result.blocked is False


def test_plots_active_set_from_ranked_today_len():
    qc = FakeQC(ranked_today=["AAPL", "MSFT", "GOOG"])
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc, ["AAPL", "MSFT"]))
    # active_set = len(_ranked_today) = 3 ; ranked = len(ranked_candidates) = 2
    assert ("Universe", "active_set", 3) in qc.plots
    assert ("Universe", "ranked", 2) in qc.plots
    assert result.facts == {"active_set": 3, "ranked": 2}


def test_empty_ranked_today_plots_zero():
    qc = FakeQC(ranked_today=[])
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    phase.evaluate(_ctx(qc, []))
    assert ("Universe", "active_set", 0) in qc.plots
    assert ("Universe", "ranked", 0) in qc.plots


def test_ranked_today_absent_plots_zero():
    qc = FakeQC(has_ranked_attr=False)  # no _ranked_today attribute at all
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc, []))
    assert ("Universe", "active_set", 0) in qc.plots
    assert result.facts["active_set"] == 0


def test_ranked_today_none_plots_zero():
    qc = FakeQC(ranked_today=None)
    qc._ranked_today = None  # explicitly None, not just empty
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    phase.evaluate(_ctx(qc, []))
    assert ("Universe", "active_set", 0) in qc.plots


def test_custom_chart_name():
    qc = FakeQC(ranked_today=["AAPL"])
    phase = ChartEmit(ChartEmit.Params(chart_name="Diag"), logger=None)
    phase.evaluate(_ctx(qc, ["AAPL"]))
    assert ("Diag", "active_set", 1) in qc.plots
    assert ("Diag", "ranked", 1) in qc.plots


def test_no_plot_attr_is_graceful_noop():
    qc = FakeQCNoPlot(ranked_today=["AAPL", "MSFT"])
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    # Must NOT raise AttributeError; still returns facts with the computed counts.
    result = phase.evaluate(_ctx(qc, ["AAPL"]))
    assert result.blocked is False
    assert result.facts == {"active_set": 2, "ranked": 1}
