import pytest
from engine.context import BarState, PhaseContext, OrderIntent, BlockEvent


def test_bar_state_starts_empty():
    bs = BarState()
    assert bs.ranked_candidates == []
    assert bs.sized_orders == []
    assert bs.add_intents == []
    assert bs.exit_intents == []
    assert bs.trim_intents == []
    assert bs.blocks == []
    assert bs.phase_outputs == {}


def test_bar_state_apply_stores_output():
    bs = BarState()
    result = object()
    bs.apply("signal", result, module="bct_score_v1")
    assert bs.phase_outputs["signal"][0] is result


def test_bar_state_apply_accumulates_list_phases():
    bs = BarState()
    r1, r2 = object(), object()
    bs.apply("regime", r1, module="vix_threshold_v1")
    bs.apply("regime", r2, module="spy_200ma_v1")
    assert len(bs.phase_outputs["regime"]) == 2
    assert bs.phase_outputs["regime"][0] is r1
    assert bs.phase_outputs["regime"][1] is r2


def test_bar_state_apply_rejects_true_double_write():
    bs = BarState()
    bs.apply("signal", object(), module="bct_score_v1")
    with pytest.raises(ValueError, match="double-write"):
        bs.apply("signal", object(), module="bct_score_v1")


def test_bar_state_apply_allows_different_modules_same_kind():
    bs = BarState()
    bs.apply("exit_hard", object(), module="cloud_breach_v1")
    bs.apply("exit_hard", object(), module="weekly_kijun_v1")  # must not raise


def test_order_intent_fields():
    oi = OrderIntent(ticker="AAPL", qty=10, price=150.0, stop=145.0, module="sizing.risk_based_fixed", risk_dollars=500.0)
    assert oi.ticker == "AAPL"
    assert oi.qty == 10


def test_block_event_fields():
    be = BlockEvent(ticker="AAPL", kind="eligibility", reason="already held", module="eligibility.already_held_check")
    assert be.kind == "eligibility"


def test_phase_context_holds_lean_refs_and_bar_state():
    class FakeQC:
        pass
    qc = FakeQC()
    from datetime import datetime
    t = datetime(2025, 1, 2)
    ctx = PhaseContext(qc=qc, time=t, data=None)
    assert ctx.qc is qc
    assert ctx.time == t
    assert isinstance(ctx.bar_state, BarState)


def test_phase_context_bar_state_fresh_each_construction():
    class FakeQC:
        pass
    qc = FakeQC()
    from datetime import datetime
    t = datetime(2025, 1, 2)
    ctx1 = PhaseContext(qc=qc, time=t, data=None)
    ctx2 = PhaseContext(qc=qc, time=t, data=None)
    assert ctx1.bar_state is not ctx2.bar_state
