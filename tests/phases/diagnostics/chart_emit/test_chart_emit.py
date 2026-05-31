"""chart_emit phase tests (#243).

Constructor mirrors the diagnostics convention: ChartEmit(ChartEmit.Params(...), logger).
FakeQC captures plot() calls as (chart, series, value) tuples. A FakeQC WITHOUT a plot
attribute must no-op gracefully (no AttributeError) — the getattr-guard for test fakes.
"""
from datetime import datetime

from engine.context import BarState, OrderIntent, PhaseContext
from phases.diagnostics.chart_emit.chart_emit import _SCORE_PROBES, ChartEmit


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


# ---- #243 fakes for the extended regime / signal-breadth / probe-score series ----


class _FakeIndicator:
    def __init__(self, value, ready=True):
        self.is_ready = ready
        self.current = type("C", (), {"value": value})()


class _FakeSymbol:
    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        return isinstance(other, _FakeSymbol) and other.value == self.value


class _FakeSecurity:
    def __init__(self, price):
        self.price = price


class FakeQCRich(FakeQC):
    """FakeQC that also carries spy / spy_sma200 / securities for the Regime block.

    score_symbol_native is monkeypatched in the probe tests, so _active / _indicators
    only need to be present + the symbol resolvable; the indicator internals are stubbed.
    """

    def __init__(self, *, spy_price=None, spy_ma200=None, sma_ready=True,
                 active=None, indicators=None, has_spy=True):
        super().__init__(ranked_today=[])
        if has_spy:
            self.spy = _FakeSymbol("SPY")
            self.spy_sma200 = _FakeIndicator(spy_ma200, ready=sma_ready)
            self.securities = {self.spy: _FakeSecurity(spy_price)}
        self._active = active if active is not None else set()
        self._indicators = indicators if indicators is not None else {}


def _ctx(qc, ranked_candidates=None, sized_orders=None):
    bs = BarState(ranked_candidates=list(ranked_candidates or []))
    if sized_orders is not None:
        bs.sized_orders = list(sized_orders)
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None, bar_state=bs)


def _order(ticker):
    return OrderIntent(ticker=ticker, qty=0, price=1.0, stop=0.0, module="t", risk_dollars=0.0)


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
    assert result.facts["active_set"] == 3
    assert result.facts["ranked"] == 2


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
    assert result.facts["active_set"] == 2
    assert result.facts["ranked"] == 1


# ============================ #243 extended series ============================


def test_regime_series_plotted_when_ready():
    qc = FakeQCRich(spy_price=500.0, spy_ma200=480.0, sma_ready=True)
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc))
    assert ("Regime", "spy_close", 500.0) in qc.plots
    assert ("Regime", "spy_ma200", 480.0) in qc.plots
    assert result.facts["regime_charted"] is True


def test_regime_skipped_when_sma_not_ready():
    # not-ready SMA must SKIP the regime series (never plot a misleading 0).
    qc = FakeQCRich(spy_price=500.0, spy_ma200=480.0, sma_ready=False)
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc))
    assert not any(c == "Regime" for c, _s, _v in qc.plots)
    assert result.facts["regime_charted"] is False


def test_regime_skipped_when_spy_missing():
    qc = FakeQCRich(has_spy=False)
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc))
    assert not any(c == "Regime" for c, _s, _v in qc.plots)
    assert result.facts["regime_charted"] is False


def test_signal_breadth_equals_sized_orders_len():
    qc = FakeQCRich(spy_price=500.0, spy_ma200=480.0)
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    orders = [_order("AAPL"), _order("MSFT"), _order("NVDA")]
    result = phase.evaluate(_ctx(qc, sized_orders=orders))
    assert ("Signal", "n_qualifying", 3) in qc.plots
    assert result.facts["n_qualifying"] == 3


def test_probe_sentinel_when_not_active():
    # No probe is subscribed → every probe series plots the -1.0 sentinel.
    qc = FakeQCRich(spy_price=500.0, spy_ma200=480.0)
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc))
    for ticker in _SCORE_PROBES:
        assert ("Score", ticker, -1.0) in qc.plots
        assert result.facts["probe_scores"][ticker] == -1.0


def test_probe_score_plotted_when_active_and_ready(monkeypatch):
    # A subscribed probe with ready indicators → its recomputed score is plotted.
    from phases.diagnostics.chart_emit import chart_emit as ce

    dri = _FakeSymbol("DRI")
    qc = FakeQCRich(
        spy_price=500.0, spy_ma200=480.0,
        active={dri},
        indicators={dri: {"sentinel": "ind-dict"}},
    )
    monkeypatch.setattr(ce, "score_symbol_native", lambda _q, _s, _i: {"score": 7, "rating": "++"})
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    result = phase.evaluate(_ctx(qc))
    assert ("Score", "DRI", 7.0) in qc.plots
    assert result.facts["probe_scores"]["DRI"] == 7.0
    # the OTHER probes are still sentinel
    assert ("Score", "CME", -1.0) in qc.plots


def test_probe_sentinel_when_scorer_returns_none(monkeypatch):
    from phases.diagnostics.chart_emit import chart_emit as ce

    dri = _FakeSymbol("DRI")
    qc = FakeQCRich(spy_price=500.0, spy_ma200=480.0, active={dri}, indicators={dri: {}})
    monkeypatch.setattr(ce, "score_symbol_native", lambda _q, _s, _i: None)
    phase = ChartEmit(ChartEmit.Params(), logger=None)
    phase.evaluate(_ctx(qc))
    assert ("Score", "DRI", -1.0) in qc.plots


def test_charting_is_inert_sized_orders_unchanged():
    # CHARTING MUST NOT MUTATE TRADING STATE. Feed a populated sized_orders, run evaluate,
    # assert the list is byte-identical afterwards (charting is read-only observability).
    qc = FakeQCRich(spy_price=500.0, spy_ma200=480.0)
    orders = [_order("AAPL"), _order("MSFT")]
    ctx = _ctx(qc, sized_orders=orders)
    same_list = ctx.bar_state.sized_orders          # the live list object
    before = list(same_list)                        # contents snapshot
    ChartEmit(ChartEmit.Params(), logger=None).evaluate(ctx)
    assert ctx.bar_state.sized_orders is same_list  # evaluate did NOT swap the list object
    assert ctx.bar_state.sized_orders == before     # ...nor mutate its contents


def test_config_hash_unchanged_champion_pin():
    # config_hash REGRESSION GUARD (#243): the extended ChartEmit must NOT bump the champion
    # pin. A future Param-creep that perturbs e573e84b1ce1 fails LOUD here.
    from engine.engine import _config_hash
    from strategies.champion_asis import CONFIG

    assert _config_hash(CONFIG) == "e573e84b1ce1"
