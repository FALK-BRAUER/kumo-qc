from datetime import datetime
from engine.context import PhaseContext, BarState
from phases.regime.vix_ichimoku_tier.vix_ichimoku_tier import VixIchimokuTier


class FakeIchi:
    def __init__(self, senkou_a, senkou_b, ready=True):
        self.is_ready = ready
        self.senkou_a = type("V", (), {"current": type("C", (), {"value": senkou_a})()})()
        self.senkou_b = type("V", (), {"current": type("C", (), {"value": senkou_b})()})()


class FakeSecurity:
    def __init__(self, price):
        self.price = price


class FakeSecurities(dict):
    def contains_key(self, key):
        return key in self


class FakeQC:
    def __init__(self, vix_price, cloud_a, cloud_b, gate_enabled=True):
        self.vix = "VIX_SYM"
        self.vix_ichi = FakeIchi(cloud_a, cloud_b)
        self.securities = FakeSecurities({"VIX_SYM": FakeSecurity(vix_price)})
        self.regime_gate_enabled = gate_enabled


def make_ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)


def test_vix_above_cloud_top_sets_tier2_unlimited():
    qc = FakeQC(vix_price=30.0, cloud_a=20.0, cloud_b=18.0)  # cloud_top=20, VIX=30 > top
    phase = VixIchimokuTier(params={}, logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)
    assert result.blocked is False
    vix_tier = ctx.bar_state.phase_outputs.get("vix_tier", [{}])[-1]
    assert vix_tier["tier"] == 2
    assert vix_tier["max_positions"] == 9999


def test_vix_below_cloud_top_sets_tier1():
    qc = FakeQC(vix_price=15.0, cloud_a=20.0, cloud_b=18.0)  # cloud_top=20, VIX=15 < top
    phase = VixIchimokuTier(params={"max_positions": 5}, logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)
    assert result.blocked is False  # NEVER blocks
    vix_tier = ctx.bar_state.phase_outputs.get("vix_tier", [{}])[-1]
    assert vix_tier["tier"] == 1
    assert vix_tier["max_positions"] == 5


def test_vix_ichimoku_tier_never_blocks():
    qc = FakeQC(vix_price=50.0, cloud_a=20.0, cloud_b=18.0)
    phase = VixIchimokuTier(params={}, logger=None)
    result = phase.evaluate(make_ctx(qc))
    assert result.blocked is False


def test_gate_disabled_passes_with_default_capacity():
    qc = FakeQC(vix_price=50.0, cloud_a=20.0, cloud_b=18.0, gate_enabled=False)
    phase = VixIchimokuTier(params={"max_positions": 10}, logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)
    assert result.blocked is False
    vix_tier = ctx.bar_state.phase_outputs.get("vix_tier", [{}])[-1]
    assert vix_tier["max_positions"] == 10
