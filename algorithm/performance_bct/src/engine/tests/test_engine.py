import pytest
from datetime import datetime
from engine.engine import StrategyEngine, PHASE_ORDER, FireSentinel, FIRE_ENTRIES, FIRE_EXITS, FIRE_ADDS, FIRE_TRIMS
from engine.base import CharterViolation
from engine.context import PhaseContext
from engine.tests.fixtures.stub_phases import make_stub


class FakeQC:
    def __init__(self):
        self.logged = []
        self.orders = []
        self._active = set()
        self.securities = {}
        self._position_meta = {}

    def Log(self, msg):
        self.logged.append(msg)

    def log(self, msg):
        self.logged.append(msg)

    def market_on_open_order(self, symbol, qty):
        self.orders.append((symbol, qty))


def make_ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)


def minimal_config(phases_override=None):
    phases = {
        "signal": {"module": "stub", "enabled": True, "params": {}},
        "portfolio_risk": {"module": "stub", "enabled": True, "params": {"max_pct": 100}},
    }
    if phases_override:
        phases.update(phases_override)
    return {
        "name": "test-strategy",
        "version": "1.0.0",
        "phases": phases,
        "invariants": {"no_count_caps": True, "no_time_exits": True, "explicit_exposure_only": True},
    }


def test_phase_order_contains_sentinels():
    assert FIRE_ENTRIES in PHASE_ORDER
    assert FIRE_EXITS in PHASE_ORDER
    assert FIRE_ADDS in PHASE_ORDER
    assert FIRE_TRIMS in PHASE_ORDER


def test_phase_order_sentinels_are_fire_sentinel_instances():
    for item in PHASE_ORDER:
        if not isinstance(item, str):
            assert isinstance(item, FireSentinel)


def test_phase_order_fire_entries_after_cash():
    str_items = [str(p) for p in PHASE_ORDER]
    cash_idx = str_items.index("cash")
    entries_idx = str_items.index("FIRE_ENTRIES")
    assert entries_idx > cash_idx


def test_phase_order_fire_exits_after_exit_hard():
    str_items = [str(p) for p in PHASE_ORDER]
    exit_idx = str_items.index("exit_hard")
    exits_fire_idx = str_items.index("FIRE_EXITS")
    assert exits_fire_idx > exit_idx


def test_phase_order_diagnostics_then_circuit_breaker_last():
    str_phases = [str(p) for p in PHASE_ORDER if isinstance(p, str)]
    assert str_phases[-2] == "diagnostics"
    assert str_phases[-1] == "circuit_breaker"


def test_engine_charter_violation_on_count_cap():
    config = minimal_config({"sizing": {"module": "stub", "enabled": True, "params": {"max_positions": 10}}})
    with pytest.raises(CharterViolation, match="max_positions"):
        StrategyEngine(config=config, qc=FakeQC(), phase_instances={})


def test_engine_charter_violation_on_max_adds():
    config = minimal_config({"adds": {"module": "stub", "enabled": True, "params": {"max_adds": 3}}})
    with pytest.raises(CharterViolation, match="max_adds"):
        StrategyEngine(config=config, qc=FakeQC(), phase_instances={})


def test_engine_runs_enabled_phases():
    qc = FakeQC()
    signal_stub = make_stub("signal")
    engine = StrategyEngine(config=minimal_config(), qc=qc, phase_instances={"signal": [signal_stub]})
    engine.on_data_with_ctx(make_ctx(qc))
    assert signal_stub.called


def test_engine_skips_disabled_phases():
    qc = FakeQC()
    signal_stub = make_stub("signal")
    signal_stub._params = {"enabled": False}
    engine = StrategyEngine(config=minimal_config(), qc=qc, phase_instances={"signal": [signal_stub]})
    engine.on_data_with_ctx(make_ctx(qc))
    assert not signal_stub.called


def test_blocked_bar_still_runs_diagnostics_and_circuit_breaker():
    qc = FakeQC()
    regime_stub = make_stub("regime", blocked=True)
    diag_stub = make_stub("diagnostics")
    cb_stub = make_stub("circuit_breaker")
    engine = StrategyEngine(
        config=minimal_config(),
        qc=qc,
        phase_instances={
            "regime": [regime_stub],
            "diagnostics": [diag_stub],
            "circuit_breaker": [cb_stub],
        },
    )
    engine.on_data_with_ctx(make_ctx(qc))
    assert regime_stub.called
    assert diag_stub.called
    assert cb_stub.called


def test_blocked_bar_skips_entry_phases():
    qc = FakeQC()
    regime_stub = make_stub("regime", blocked=True)
    sizing_stub = make_stub("sizing")
    engine = StrategyEngine(
        config=minimal_config(),
        qc=qc,
        phase_instances={"regime": [regime_stub], "sizing": [sizing_stub]},
    )
    engine.on_data_with_ctx(make_ctx(qc))
    assert sizing_stub.called is False


def test_blocked_bar_still_runs_exit_phases():
    """Regime block halts entries only. Exit phases (trail, exit_hard) must run."""
    qc = FakeQC()
    regime_stub = make_stub("regime", blocked=True)
    trail_stub = make_stub("trail")
    exit_stub = make_stub("exit_hard")
    engine = StrategyEngine(
        config=minimal_config(),
        qc=qc,
        phase_instances={
            "regime": [regime_stub],
            "trail": [trail_stub],
            "exit_hard": [exit_stub],
        },
    )
    engine.on_data_with_ctx(make_ctx(qc))
    assert trail_stub.called
    assert exit_stub.called


def test_engine_logs_strategy_init():
    qc = FakeQC()
    StrategyEngine(config=minimal_config(), qc=qc, phase_instances={})
    assert any("STRATEGY_INIT" in line for line in qc.logged)
