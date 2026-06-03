"""#276b-1 — PreFlightStaleness: the ASYMMETRIC pre-flight gap-gate (the GH#25 staleness guard).

Methodology pillar (#244): per-phase behavioral FIRE + DECLINE, on dummy inputs. The HQ-mandated
asymmetric cases are explicit: a +5% gap-up is NOT invalidated (George's norm, BCT-6 mean +5.1%);
a gap-down OR a close below the daily Kijun IS invalidated. Pure-core golden-master + a phase test.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.preflight_staleness.preflight_staleness import (
    PreFlightStaleness,
    preflight_valid,
)

SIG = 100.0   # signal price
KIJUN = 95.0  # daily Kijun (below signal — the structural floor)


def _valid(current, **kw):
    kw.setdefault("signal_price", SIG); kw.setdefault("daily_kijun", KIJUN)
    kw.setdefault("gap_up_tolerance_pct", 0.10); kw.setdefault("below_kijun_invalidates", True)
    return preflight_valid(current_price=current, **kw)


# ── PURE asymmetric decision (golden-master) ──

def test_gap_up_5pct_is_NOT_invalidated() -> None:
    # HQ-MANDATED: a +5% gap-up (George's norm, BCT-6 mean +5.1%) within the 10% tolerance → VALID.
    ok, reason = _valid(105.0)
    assert ok is True and reason == "ok", "a +5% gap-up must NOT be invalidated (George's norm)"


def test_gap_down_below_kijun_IS_invalidated() -> None:
    # HQ-MANDATED: a gap-DOWN that closes BELOW the daily Kijun → INVALID (thesis broken).
    ok, reason = _valid(94.0)  # below KIJUN=95 and below SIG=100
    assert ok is False and reason == "below_daily_kijun"


def test_gap_down_above_kijun_invalidated() -> None:
    # a gap-DOWN that's still above the Kijun → INVALID (thesis weakened; George enters on gap-UPS).
    ok, reason = _valid(98.0)  # < SIG=100, > KIJUN=95
    assert ok is False and reason == "gap_down"


def test_excessive_gap_up_invalidated() -> None:
    # a runaway gap-up beyond the tolerance → INVALID (don't chase).
    ok, reason = _valid(112.0)  # +12% > 10% tol
    assert ok is False and reason == "excessive_gap_up"


def test_at_signal_and_small_gap_up_valid() -> None:
    assert _valid(100.0) == (True, "ok")   # exactly at signal
    assert _valid(108.0) == (True, "ok")   # +8% gap-up, within tol


def test_degraded_signal_price_invalid() -> None:
    ok, reason = _valid(105.0, signal_price=0.0)
    assert ok is False and reason == "degraded_signal_price"


def test_below_kijun_toggle_off_allows_below_kijun() -> None:
    # MUTATION-BITE control: below_kijun_invalidates=False → a (gap-up) name below Kijun is NOT
    # killed by the Kijun rule (proves that rule is what bites in test_gap_down_below_kijun).
    ok, reason = _valid(105.0, daily_kijun=110.0, below_kijun_invalidates=False)
    assert ok is True and reason == "ok"  # 105 is a +5% gap-up; Kijun rule off → allowed


# ── PHASE (reads snapshot + intraday close, filters sized_orders) ──

class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _FakeQC:
    def __init__(self, snaps, last_closes):
        self._snaps = snaps              # sym -> snapshot dict (or None for H1)
        self._active = set(snaps)
        self._intraday = {s: {"last_close": last_closes.get(s)} for s in snaps}
        self.logged = []

    def log(self, m): self.logged.append(m)

    def snapshot_for_entry(self, sym):
        return self._snaps.get(sym)  # None → H1 not-enterable


def _phase(**kw):
    return PreFlightStaleness(PreFlightStaleness.Params(**kw), logger=None)


def _ctx(qc, tickers):
    c = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    c.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)
        for t in tickers
    ]
    return c


def test_phase_keeps_valid_gap_up_drops_stale() -> None:
    good, bad = _Sym("AAPL"), _Sym("TSLA")
    snaps = {
        good: {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"},
        bad:  {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"},
    }
    qc = _FakeQC(snaps, last_closes={good: 105.0, bad: 94.0})  # good=+5% gap-up; bad=below Kijun
    ctx = _ctx(qc, ["aapl", "tsla"])
    _phase().evaluate(ctx)
    kept = [i.ticker for i in ctx.bar_state.sized_orders]
    assert kept == ["aapl"], "valid gap-up kept, gap-down-below-Kijun dropped"


def test_phase_h1_no_snapshot_drops_candidate() -> None:
    # H1 (276b-0): a candidate with NO decided thesis (snapshot_for_entry → None) is dropped.
    ghost = _Sym("GHOST")
    qc = _FakeQC({ghost: None}, last_closes={ghost: 105.0})
    ctx = _ctx(qc, ["ghost"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []


def test_phase_never_blocks_the_bar() -> None:
    good = _Sym("AAPL")
    qc = _FakeQC({good: {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"}},
                 last_closes={good: 105.0})
    res = _phase().evaluate(_ctx(qc, ["aapl"]))
    assert res.blocked is False


def test_phase_stale_snapshot_raises_via_accessor() -> None:
    # H2 propagates: if the accessor raises on a stale snapshot, the phase does not swallow it.
    good = _Sym("AAPL")

    class _StaleQC(_FakeQC):
        def snapshot_for_entry(self, sym):
            raise DegradedDataError("stale candidate snapshot (#276b-0 H2)")

    qc = _StaleQC({good: {}}, last_closes={good: 105.0})
    with pytest.raises(DegradedDataError, match="stale"):
        _phase().evaluate(_ctx(qc, ["aapl"]))


def test_space_and_complexity_declared() -> None:
    assert "gap_up_tolerance_pct" in PreFlightStaleness.Params.space().axes
    assert PreFlightStaleness.COMPLEXITY.free_params == 1
