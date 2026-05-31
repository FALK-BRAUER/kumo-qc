"""Behavioral contract (#245) for the version_marker diagnostics phase.

v2-delta: constructor is VersionMarker(VersionMarker.Params(...), logger=None).

Upgraded from substring-only: the REBALANCE log fields (open / new_entries / exits)
must MATCH the bar_state contents, and the `open` count must come from the LAST sizing
phase output's facts (src ~:43 — sizing_outputs[-1].facts['open']). We populate the bar
state with real sized_orders + exit_intents + a sizing PhaseResult and parse the log.
"""
from datetime import datetime

from engine.base import PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.diagnostics.version_marker.version_marker import VersionMarker


class FakeQC:
    def __init__(self):
        self.logged = []
    def log(self, msg):
        self.logged.append(msg)


def _rebalance_fields(qc):
    """Parse the single REBALANCE|date|open=..|new_entries=..|exits=.. log line into a dict."""
    line = next(m for m in qc.logged if m.startswith("REBALANCE|"))
    parts = line.split("|")
    fields = {}
    for p in parts[2:]:
        k, _, v = p.partition("=")
        fields[k] = int(v)
    return fields


def _order(ticker):
    return OrderIntent(ticker=ticker, qty=0, price=1.0, stop=0.0, module="t", risk_dollars=0.0)


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


# ---------------------------------------------------------------------------
# Counts MATCH bar_state, and `open` comes from the populated sizing output (#245).
# ---------------------------------------------------------------------------
def test_rebalance_counts_match_populated_bar_state():
    qc = FakeQC()
    phase = VersionMarker(VersionMarker.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 15), data=None)

    # Populate the bar state as upstream phases would have.
    ctx.bar_state.sized_orders = [_order("AAPL"), _order("MSFT")]      # → new_entries = 2
    ctx.bar_state.exit_intents = [_order("TSLA")]                       # → exits = 1
    # A populated sizing phase output whose facts carry the open count (src reads facts['open']).
    sizing_result = PhaseResult(
        decision=None, blocked=False, reason="sized", facts={"open": 5}, metrics={}
    )
    ctx.bar_state.phase_outputs["sizing"] = [sizing_result]

    result = phase.evaluate(ctx)

    fields = _rebalance_fields(qc)
    assert fields["open"] == 5          # from sizing_outputs[-1].facts['open']
    assert fields["new_entries"] == 2   # == len(sized_orders)
    assert fields["exits"] == 1         # == len(exit_intents)
    # facts on the returned result mirror the same counts.
    assert result.facts["entries"] == 2
    assert result.facts["exits"] == 1


def test_rebalance_uses_last_sizing_output_for_open():
    # src takes sizing_outputs[-1] — the LAST output's open, not the first.
    qc = FakeQC()
    phase = VersionMarker(VersionMarker.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 15), data=None)
    ctx.bar_state.phase_outputs["sizing"] = [
        PhaseResult(decision=None, blocked=False, reason="a", facts={"open": 3}, metrics={}),
        PhaseResult(decision=None, blocked=False, reason="b", facts={"open": 9}, metrics={}),
    ]
    phase.evaluate(ctx)
    assert _rebalance_fields(qc)["open"] == 9


def test_rebalance_open_defaults_zero_without_sizing_output():
    # EDGE: no sizing output at all → open defaults to 0; entries/exits reflect empty lists.
    qc = FakeQC()
    phase = VersionMarker(VersionMarker.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 15), data=None)
    phase.evaluate(ctx)
    fields = _rebalance_fields(qc)
    assert fields == {"open": 0, "new_entries": 0, "exits": 0}


def test_rebalance_open_defaults_zero_when_sizing_facts_lack_open():
    # EDGE: sizing output present but its facts omit 'open' → facts.get('open', 0) → 0.
    qc = FakeQC()
    phase = VersionMarker(VersionMarker.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 15), data=None)
    ctx.bar_state.phase_outputs["sizing"] = [
        PhaseResult(decision=None, blocked=False, reason="no-open", facts={}, metrics={})
    ]
    ctx.bar_state.sized_orders = [_order("NVDA")]
    phase.evaluate(ctx)
    fields = _rebalance_fields(qc)
    assert fields["open"] == 0
    assert fields["new_entries"] == 1
