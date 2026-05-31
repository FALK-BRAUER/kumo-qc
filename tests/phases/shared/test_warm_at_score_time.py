"""#264 — the LOAD-BEARING "not-warm at SCORE time" matrix (the next-mirage catcher).

PRINCIPLE (Falk, hard): an UNWARMED / not-ready indicator must NEVER silently produce a score.
That IS the mirage that produced the fake −0.616 baseline — unwarmed indicators "woke up in
October", and a name that should have been EXCLUDED instead contributed a number from partial
state. A not-ready indicator at score time must SKIP-LOUD (excluded, no score) or RAISE — never
a number off partial state.

This file is exhaustive on the SCORE-TIME readiness gate of BOTH scorers that consume the
maintained suite:

  - score_symbol_native (phases.shared.oracle_helpers)  — the 8-condition SIGNAL qualifier.
    Readiness gate: oracle_helpers.py L148-151 (every named indicator + the two window counts).
  - BctEntryConfirm._score_candidate (entry_selection)  — the §4 Gate-2 ENTRY confirmation.
    Readiness gate: bct_entry_confirm.py L291-306.

For EACH indicator the suite reads, we assert: when that indicator (or its rolling window) is
NOT ready, the scorer returns None (skip-loud) — it does NOT emit a score off partial state.

WHERE THE ENGINE IS CORRECT vs. WHERE IT IS A GAP:
Both maintained scorers ALREADY fail-loud correctly (return None on any not-ready input). The
two FAIL-OPEN / SILENT-SKIP boundaries this audit found are in OTHER phases and are NOT score-
emitters, so they are flagged for #261 (see test_warm_engine_boundaries.py), not asserted as
broken here. This file pins the maintained-scorer fail-loud contract so a future refactor that
makes either scorer lenient (scores on a not-ready input) FAILS LOUDLY in CI.

Fakes mirror the QC accessor shapes used project-wide (test_score_symbol_native / fake_qc):
.current.value / .is_ready / .positive_directional_index / RollingWindow[i] + .count.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import BctEntryConfirm
from phases.shared.oracle_helpers import score_symbol_native


# ======================================================================================
# Shared QC-accessor fakes
# ======================================================================================
class _Cur:
    def __init__(self, v: float) -> None:
        self.value = v


class _Ind:
    def __init__(self, v: float, ready: bool = True) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    def __init__(self, tenkan: float, kijun: float, sa: float, sb: float, ready: bool = True) -> None:
        self.tenkan = _Ind(tenkan)
        self.kijun = _Ind(kijun)
        self.senkou_a = _Ind(sa)
        self.senkou_b = _Ind(sb)
        self.is_ready = ready


class _Adx:
    def __init__(self, adx: float, pdi: float, ndi: float, ready: bool = True) -> None:
        self.current = _Cur(adx)
        self.positive_directional_index = _Ind(pdi)
        self.negative_directional_index = _Ind(ndi)
        self.is_ready = ready


class _Macd:
    def __init__(self, ready: bool = True) -> None:
        self.is_ready = ready


class _Window:
    def __init__(self, vals: list[float]) -> None:
        self._v = vals  # index 0 = most recent

    def __getitem__(self, i: int) -> float:
        return self._v[i]

    @property
    def count(self) -> int:
        return len(self._v)


class _TBounce:
    def __init__(self, last_close: float | None = 100.0) -> None:
        self.sessions_below_tenkan = 0
        self.gap_up_frac = 0.0
        self.last_open = 99.6
        self.last_high = 100.2
        self.last_low = 99.5
        self.last_close = last_close


class _Sec:
    def __init__(self, price: float, volume: float = 200_000.0) -> None:
        self.price = price
        self.volume = volume


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


# ======================================================================================
# PART A — score_symbol_native (the SIGNAL qualifier) fail-loud-at-score-time
# ======================================================================================
class _SignalQC:
    def __init__(self, price: float) -> None:
        self.securities = {"SYM": _Sec(price)}


def _signal_ready_ind(**over: Any) -> dict[str, Any]:
    """8/8-passing maintained set at price=100 (mirror of fake_qc.all_pass_indicators, the
    SIGNAL subset). Override one key to toggle a single indicator to NOT-ready."""
    base: dict[str, Any] = {
        "d_ichi": _Ichi(tenkan=90.0, kijun=88.0, sa=85.0, sb=80.0),
        "w_ichi": _Ichi(tenkan=70.0, kijun=60.0, sa=75.0, sb=65.0),
        "w_close": _Window([90.0] + [50.0] * 26),
        "sma200": _Ind(50.0),
        "adx": _Adx(adx=25.0, pdi=30.0, ndi=10.0),
        "adx_window": _Window([25.0, 24.0, 23.0, 22.0]),
        "roc13": _Ind(0.10),
    }
    base.update(over)
    return base


def _signal_score(ind: dict[str, Any], price: float = 100.0):
    return score_symbol_native(_SignalQC(price), "SYM", ind)


def test_signal_warm_set_scores_8():
    # CONTROL: the fully-warm set DOES score (proves the matrix toggles a real difference).
    r = _signal_score(_signal_ready_ind())
    assert r is not None and r["score"] == 8


# --- every NAMED indicator not-ready -> None (skip-loud), per-indicator. ---
@pytest.mark.parametrize(
    "key,not_ready",
    [
        ("d_ichi", _Ichi(90, 88, 85, 80, ready=False)),
        ("w_ichi", _Ichi(70, 60, 75, 65, ready=False)),
        ("sma200", _Ind(50.0, ready=False)),
        ("adx", _Adx(25, 30, 10, ready=False)),
        ("roc13", _Ind(0.10, ready=False)),
    ],
)
def test_signal_indicator_not_ready_returns_none(key: str, not_ready: Any):
    # The mirage guard: a not-ready indicator -> None, NOT a score off partial state.
    assert _signal_score(_signal_ready_ind(**{key: not_ready})) is None


# --- rolling WINDOWS not-full -> None (the cascade child must not read short). ---
def test_signal_w_close_window_too_short_returns_none():
    # chikou (cond 3) needs w_close[26]; <27 entries -> None.
    assert _signal_score(_signal_ready_ind(w_close=_Window([90.0] + [50.0] * 25))) is None  # 26 < 27


def test_signal_w_close_exactly_27_is_ready():
    # Boundary: exactly 27 entries -> w_close[26] exists -> scores (not over-strict).
    r = _signal_score(_signal_ready_ind(w_close=_Window([90.0] + [50.0] * 26)))
    assert r is not None


def test_signal_adx_window_too_short_returns_none():
    # adx_rising = adx_window[0] > adx_window[3]; needs count >= 4. count 3 -> None.
    assert _signal_score(_signal_ready_ind(adx_window=_Window([25.0, 24.0, 23.0]))) is None


def test_signal_adx_window_exactly_4_is_ready():
    r = _signal_score(_signal_ready_ind(adx_window=_Window([25.0, 24.0, 23.0, 22.0])))
    assert r is not None


def test_signal_all_indicators_cold_returns_none():
    # EVERYTHING not ready -> None (the full "fresh mid-FY entrant before its seed" state).
    cold = {
        "d_ichi": _Ichi(0, 0, 0, 0, ready=False),
        "w_ichi": _Ichi(0, 0, 0, 0, ready=False),
        "w_close": _Window([]),
        "sma200": _Ind(0.0, ready=False),
        "adx": _Adx(0, 0, 0, ready=False),
        "adx_window": _Window([]),
        "roc13": _Ind(0.0, ready=False),
    }
    assert _signal_score(cold) is None


def test_signal_nonpositive_price_returns_none():
    # Even fully warm, a 0/neg price (no live tick yet) -> None (not a score off a bad price).
    assert _signal_score(_signal_ready_ind(), price=0.0) is None
    assert _signal_score(_signal_ready_ind(), price=-1.0) is None


# ======================================================================================
# PART B — BctEntryConfirm._score_candidate (the ENTRY confirmation) fail-loud-at-score-time
# ======================================================================================
class _EntryQC:
    def __init__(self) -> None:
        self._active: set[Any] = set()
        self.securities: dict[Any, _Sec] = {}
        self._indicators: dict[Any, dict[str, Any]] = {}


def _entry_ready_ind(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "d_ichi": _Ichi(tenkan=99.7, kijun=95.0, sa=90.0, sb=80.0),
        "macd": _Macd(ready=True),
        "macd_hist_window": _Window([0.5, 0.2]),
        "vol_sma20": _Ind(100_000.0),
        "tbounce": _TBounce(),
    }
    base.update(over)
    return base


def _entry_score(ind: dict[str, Any] | None, *, price: float = 100.0):
    """Drive _score_candidate directly (the SCORE-TIME readiness path) and return the
    ComponentScore-or-None — the exact value the phase keys its confirm/decline on."""
    qc = _EntryQC()
    sym = _Sym("SYM")
    qc._active.add(sym)
    qc.securities[sym] = _Sec(price, 200_000.0)
    phase = BctEntryConfirm(BctEntryConfirm.Params(), logger=None)
    return phase._score_candidate(qc, sym, ind)


def test_entry_warm_set_scores_not_none():
    # CONTROL: a warm entry set returns a ComponentScore (not None).
    cs = _entry_score(_entry_ready_ind())
    assert cs is not None


@pytest.mark.parametrize(
    "key,not_ready",
    [
        ("d_ichi", _Ichi(99.7, 95, 90, 80, ready=False)),
        ("macd", _Macd(ready=False)),
        ("vol_sma20", _Ind(100_000.0, ready=False)),
    ],
)
def test_entry_indicator_not_ready_returns_none(key: str, not_ready: Any):
    assert _entry_score(_entry_ready_ind(**{key: not_ready})) is None


def test_entry_missing_indicator_key_returns_none():
    # Any of the four mandatory keys absent -> None (the dict.get(...) is None branch).
    for key in ("d_ichi", "macd", "vol_sma20", "macd_hist_window"):
        ind = _entry_ready_ind()
        del ind[key]
        assert _entry_score(ind) is None, f"{key} absent should decline"


def test_entry_macd_hist_window_too_short_returns_none():
    # macd_hist_window.count < 2 (can't read the turning direction macd_hist_window[1]) -> None.
    assert _entry_score(_entry_ready_ind(macd_hist_window=_Window([0.5]))) is None


def test_entry_no_daily_bar_yet_returns_none():
    # tbounce has no completed daily bar (last_close is None) -> C2 unreadable -> None. This is
    # the "subscribed but no daily bar fed yet" state — must decline, not score off no-bar.
    assert _entry_score(_entry_ready_ind(tbounce=_TBounce(last_close=None))) is None


def test_entry_tbounce_missing_returns_none():
    ind = _entry_ready_ind()
    del ind["tbounce"]
    assert _entry_score(ind) is None


def test_entry_none_indicators_returns_none():
    assert _entry_score(None) is None


def test_entry_nonpositive_price_returns_none():
    assert _entry_score(_entry_ready_ind(), price=0.0) is None


# ======================================================================================
# PART C — the PHASE-LEVEL consequence: a not-ready candidate is DECLINED, never fired.
# This closes the loop from "scorer returns None" to "the engine does not enter the name".
# ======================================================================================
def _entry_phase_decline_count(ind: dict[str, Any] | None) -> tuple[int, int]:
    qc = _EntryQC()
    sym = _Sym("SYM")
    qc._active.add(sym)
    qc.securities[sym] = _Sec(100.0, 200_000.0)
    if ind is not None:
        qc._indicators[sym] = ind
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker="SYM", qty=0, price=0.0, stop=0.0, module="signal.stub", risk_dollars=0.0)
    ]
    res = BctEntryConfirm(BctEntryConfirm.Params(), logger=None).evaluate(ctx)
    return len(ctx.bar_state.sized_orders), res.facts["declined"]


def test_entry_phase_declines_not_ready_candidate_no_fire():
    # A not-ready indicator -> _score_candidate None -> the phase DECLINES (drops the stub),
    # so NO order survives to FIRE_ENTRIES. The score-time mirage cannot reach the order tape.
    confirmed, declined = _entry_phase_decline_count(_entry_ready_ind(macd=_Macd(ready=False)))
    assert confirmed == 0 and declined == 1


def test_entry_phase_confirms_ready_candidate():
    # CONTROL: a warm + confirming candidate DOES survive (the gate is not pathologically strict).
    confirmed, _declined = _entry_phase_decline_count(_entry_ready_ind())
    assert confirmed == 1
