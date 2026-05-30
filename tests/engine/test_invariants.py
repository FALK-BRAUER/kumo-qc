from dataclasses import dataclass

import pytest

from engine.base import CharterViolation, ConfigError, DependencyError
from engine.config import Slot, StrategyConfig
from engine.engine import StrategyEngine, validate_invariants
from tests.harness.stub_phases import StubPhase, slot


class FakeQC:
    def Log(self, msg: str) -> None: ...
    def log(self, msg: str) -> None: ...


# --- a phase whose Params carries a forbidden field name (count cap) ---
class _CapPhase(StubPhase):
    @dataclass(slots=True)
    class Params:
        kind: str = "sizing"
        max_positions: int = 10  # FORBIDDEN
        enabled: bool = True

    def __init__(self, params: "_CapPhase.Params", logger: object = None) -> None:
        # build a StubPhase.Params-shaped object for the base
        super().__init__(StubPhase.Params(kind=params.kind), logger)


def test_forbidden_param_field_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "sizing": Slot(impl=_CapPhase, params=_CapPhase.Params()),
    })
    with pytest.raises(CharterViolation, match="max_positions"):
        validate_invariants(cfg)


def test_allowed_params_pass() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={"sizing": slot("sizing")})
    validate_invariants(cfg)  # must not raise


def test_adds_without_portfolio_risk_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "adds": slot("adds"),
    })
    with pytest.raises(CharterViolation, match="implicit exposure"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_adds_with_portfolio_risk_passes() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "adds": slot("adds"), "portfolio_risk": slot("portfolio_risk"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


def test_required_phase_missing_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"),  # no sizing
    })
    with pytest.raises(ConfigError, match="sizing"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_single_adds_enforced() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "portfolio_risk": slot("portfolio_risk"),
        "adds": [slot("adds"), slot("adds")],
    })
    with pytest.raises(CharterViolation, match="mutually exclusive"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_dependency_unmet_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing", requires=("ranking",)),  # ranking not enabled
    })
    with pytest.raises(DependencyError, match="ranking"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_dependency_satisfied_passes() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal", requires=("universe",)),
        "sizing": slot("sizing", requires=("signal",)),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # universe<signal<sizing in PHASE_ORDER, must not raise
