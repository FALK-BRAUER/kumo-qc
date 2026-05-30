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


# --- a phase whose Params carries a forbidden TIME-EXIT field name (max-hold) ---
class _TimeExitPhase(StubPhase):
    @dataclass(slots=True)
    class Params:
        kind: str = "exit_hard"
        max_hold_days: int = 90  # FORBIDDEN time-exit / max-hold
        enabled: bool = True

    def __init__(self, params: "_TimeExitPhase.Params", logger: object = None) -> None:
        super().__init__(StubPhase.Params(kind=params.kind), logger)


def test_forbidden_time_exit_param_raises() -> None:
    # Proves the charter-scan catches a genuine TIME-EXIT by name (not only count-caps).
    # This is the guarantee that makes phase3_days's legitimacy meaningful: a real
    # max_hold_days / exit_after_days WOULD be rejected; phase3_days passes only because
    # it is correctly absent from FORBIDDEN_PARAMS (a trail-loosen age gate, not a max-hold).
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "exit_hard": Slot(impl=_TimeExitPhase, params=_TimeExitPhase.Params()),
    })
    with pytest.raises(CharterViolation, match="max_hold_days"):
        validate_invariants(cfg)


def test_phase3_days_is_not_forbidden() -> None:
    # The legitimate Rule #13 trail-loosen age gate must NOT trip the scan — a phase
    # carrying phase3_days passes validate_invariants (not a FORBIDDEN_PARAMS name).
    class _Phase3(StubPhase):
        @dataclass(slots=True)
        class Params:
            kind: str = "exit_hard"
            phase3_days: int = 56  # Rule #13 age gate — legitimate
            enabled: bool = True

        def __init__(self, params: object, logger: object = None) -> None:
            super().__init__(StubPhase.Params(kind="exit_hard"), logger)

    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "exit_hard": Slot(impl=_Phase3, params=_Phase3.Params()),
    })
    validate_invariants(cfg)  # must NOT raise


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
        "filter": slot("filter"),
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "adds": slot("adds"), "portfolio_risk": slot("portfolio_risk"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


def test_required_phase_missing_raises() -> None:
    # filter/universe/signal present, sizing omitted -> reports the missing 'sizing'.
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "filter": slot("filter"), "universe": slot("universe"), "signal": slot("signal"),
    })
    with pytest.raises(ConfigError, match="sizing"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_filter_required_missing_raises() -> None:
    # filter is now a REQUIRED phase (explicit eligibility stage cannot be omitted).
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
    })
    with pytest.raises(ConfigError, match="filter"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_single_adds_enforced() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "filter": slot("filter"),
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "portfolio_risk": slot("portfolio_risk"),
        "adds": [slot("adds"), slot("adds")],
    })
    with pytest.raises(CharterViolation, match="mutually exclusive"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_dependency_unmet_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "filter": slot("filter"), "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing", requires=("ranking",)),  # ranking not enabled
    })
    with pytest.raises(DependencyError, match="ranking"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_dependency_satisfied_passes() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "filter": slot("filter"), "universe": slot("universe"),
        "signal": slot("signal", requires=("universe",)),
        "sizing": slot("sizing", requires=("signal",)),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # filter<universe<signal<sizing, must not raise
