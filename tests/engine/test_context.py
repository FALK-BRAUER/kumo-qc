from datetime import datetime

import pytest

from engine.context import BarState, BlockEvent, OrderIntent, PhaseContext


def test_bar_state_starts_empty() -> None:
    bs = BarState()
    assert bs.ranked_candidates == []
    assert bs.sized_orders == []
    assert bs.phase_outputs == {}


def test_bar_state_is_slots() -> None:
    bs = BarState()
    with pytest.raises(AttributeError):
        bs.not_a_field = 1  # type: ignore[attr-defined]


def test_apply_accumulates_list_phases() -> None:
    # The fixed-blocker test: multi-sub-phase kind (regime) accumulates, no false double-write.
    bs = BarState()
    r1, r2 = object(), object()
    bs.apply("regime", r1, module="vix_v1")
    bs.apply("regime", r2, module="spy_v1")
    assert bs.phase_outputs["regime"] == [r1, r2]


def test_apply_rejects_true_duplicate() -> None:
    bs = BarState()
    bs.apply("signal", object(), module="bct_v1")
    with pytest.raises(ValueError, match="double-write"):
        bs.apply("signal", object(), module="bct_v1")


def test_apply_allows_same_kind_different_module() -> None:
    bs = BarState()
    bs.apply("exit_hard", object(), module="cloud_v1")
    bs.apply("exit_hard", object(), module="weekly_v1")  # must not raise


def test_order_intent_slots() -> None:
    oi = OrderIntent(ticker="AAPL", qty=10, price=1.0, stop=0.9, module="m", risk_dollars=500.0)
    assert oi.ticker == "AAPL"


def test_phase_context_fresh_bar_state() -> None:
    c1 = PhaseContext(qc=object(), time=datetime(2025, 1, 2), data=None)
    c2 = PhaseContext(qc=object(), time=datetime(2025, 1, 2), data=None)
    assert c1.bar_state is not c2.bar_state
