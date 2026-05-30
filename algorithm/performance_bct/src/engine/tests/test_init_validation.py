import pytest
from engine.engine import StrategyEngine, validate_invariants, PHASE_ORDER
from engine.base import CharterViolation, DependencyError, ConfigError
from engine.tests.fixtures.stub_phases import StubPhase, make_stub


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


def _base_config():
    return {
        "name": "test-strategy",
        "version": "1.0.0",
        "phases": {
            "universe": {"module": "stub", "enabled": True, "params": {}},
            "signal": {"module": "stub", "enabled": True, "params": {}},
            "sizing": {"module": "stub", "enabled": True, "params": {}},
            "portfolio_risk": {"module": "stub", "enabled": True, "params": {"max_pct": 100}},
        },
        "invariants": {},
    }


# ── 1. Dependency check ────────────────────────────────────────────────

class DepPhase(StubPhase):
    REQUIRES_UPSTREAM = ["signal", "regime"]


def test_dependency_missing_upstream_raises():
    """sizing requires signal + regime, but regime is missing → DependencyError."""
    config = _base_config()
    config["phases"]["sizing"] = {"module": "stub", "enabled": True, "params": {}}
    # regime is missing entirely
    qc = FakeQC()
    with pytest.raises(DependencyError, match="regime"):
        StrategyEngine(config=config, qc=qc, phase_instances={"sizing": [DepPhase("sizing", params={}, logger=None)]})


def test_dependency_disabled_upstream_raises():
    """regime present but disabled → DependencyError."""
    config = _base_config()
    config["phases"]["regime"] = {"module": "stub", "enabled": False, "params": {}}
    qc = FakeQC()
    with pytest.raises(DependencyError, match="regime"):
        StrategyEngine(config=config, qc=qc, phase_instances={
            "sizing": [DepPhase("sizing", params={}, logger=None)],
            "signal": [make_stub("signal")],
        })


def test_dependency_satisfied_passes():
    """Both signal and regime enabled → init succeeds."""
    config = _base_config()
    config["phases"]["regime"] = {"module": "stub", "enabled": True, "params": {}}
    qc = FakeQC()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={
        "sizing": [DepPhase("sizing", params={}, logger=None)],
        "signal": [make_stub("signal")],
        "regime": [make_stub("regime")],
    })
    assert engine is not None


def test_dependency_not_required_passes():
    """Phase with empty REQUIRES_UPSTREAM never fails."""
    config = _base_config()
    qc = FakeQC()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={
        "universe": [make_stub("universe")],
        "signal": [make_stub("signal")],
        "sizing": [make_stub("sizing")],
    })
    assert engine is not None


# ── 2. Single-adds enforcement ─────────────────────────────────────────


def test_two_adds_modules_raises():
    config = _base_config()
    config["phases"]["adds"] = [
        {"module": "phases.adds.pe_signal_renewed", "enabled": True, "params": {}},
        {"module": "phases.adds.pe_rampup", "enabled": True, "params": {}},
    ]
    qc = FakeQC()
    with pytest.raises(CharterViolation, match="mutually exclusive"):
        StrategyEngine(config=config, qc=qc, phase_instances={})


def test_one_adds_module_passes():
    config = _base_config()
    config["phases"]["adds"] = {"module": "phases.adds.pe_signal_renewed", "enabled": True, "params": {}}
    qc = FakeQC()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={})
    assert engine is not None


def test_zero_adds_modules_passes():
    config = _base_config()
    qc = FakeQC()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={})
    assert engine is not None


# ── 3. Required-phases check ─────────────────────────────────────────


def test_missing_universe_raises():
    config = _base_config()
    del config["phases"]["universe"]
    qc = FakeQC()
    with pytest.raises(ConfigError, match="universe"):
        StrategyEngine(config=config, qc=qc, phase_instances={})


def test_missing_signal_raises():
    config = _base_config()
    del config["phases"]["signal"]
    qc = FakeQC()
    with pytest.raises(ConfigError, match="signal"):
        StrategyEngine(config=config, qc=qc, phase_instances={})


def test_missing_sizing_raises():
    config = _base_config()
    del config["phases"]["sizing"]
    qc = FakeQC()
    with pytest.raises(ConfigError, match="sizing"):
        StrategyEngine(config=config, qc=qc, phase_instances={})


def test_disabled_required_phase_raises():
    config = _base_config()
    config["phases"]["signal"]["enabled"] = False
    qc = FakeQC()
    with pytest.raises(ConfigError, match="signal"):
        StrategyEngine(config=config, qc=qc, phase_instances={})


def test_complete_config_passes():
    config = _base_config()
    qc = FakeQC()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={})
    assert engine is not None


# ── 4. Version-marker logging at init ────────────────────────────────


def test_init_logs_phase_loaded_for_each_phase():
    config = _base_config()
    config["phases"]["regime"] = {"module": "stub", "enabled": True, "params": {}}
    qc = FakeQC()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={
        "universe": [make_stub("universe")],
        "signal": [make_stub("signal")],
        "sizing": [make_stub("sizing")],
    })
    loaded = [line for line in qc.logged if "PHASE_LOADED" in line]
    assert len(loaded) == 3
    assert any("universe" in line and "stub_universe_v1" in line for line in loaded)
    assert any("signal" in line and "stub_signal_v1" in line for line in loaded)
    assert any("sizing" in line and "stub_sizing_v1" in line for line in loaded)


def test_init_does_not_log_disabled_phase():
    config = _base_config()
    qc = FakeQC()
    stub = make_stub("signal")
    stub._params["enabled"] = False
    engine = StrategyEngine(config=config, qc=qc, phase_instances={
        "universe": [make_stub("universe")],
        "signal": [stub],
        "sizing": [make_stub("sizing")],
    })
    loaded = [line for line in qc.logged if "PHASE_LOADED" in line]
    assert len(loaded) == 2  # universe + sizing, not signal
    assert not any("signal" in line for line in loaded)


def test_init_logs_list_phases():
    """If a phase kind is a list (e.g. regime), log each enabled sub-phase."""
    config = _base_config()
    config["phases"]["regime"] = [
        {"module": "stub", "enabled": True, "params": {}},
        {"module": "stub", "enabled": True, "params": {}},
    ]
    qc = FakeQC()
    regime1 = make_stub("regime")
    regime2 = make_stub("regime")
    engine = StrategyEngine(config=config, qc=qc, phase_instances={
        "universe": [make_stub("universe")],
        "signal": [make_stub("signal")],
        "sizing": [make_stub("sizing")],
        "regime": [regime1, regime2],
    })
    loaded = [line for line in qc.logged if "PHASE_LOADED" in line]
    assert len(loaded) == 5  # universe + signal + sizing + regime1 + regime2
    regime_loaded = [line for line in loaded if "regime" in line]
    assert len(regime_loaded) == 2
