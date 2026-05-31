import pytest

from engine.base import CharterViolation, ConfigError, DependencyError
from engine.config import Slot, StrategyConfig
from engine.engine import StrategyEngine, validate_invariants
from tests.harness.stub_phases import slot


class FakeQC:
    def Log(self, msg: str) -> None: ...
    def log(self, msg: str) -> None: ...


# FORBIDDEN_PARAMS removed (Falk directive): the no-count-caps / no-time-exits rules are
# CONVENTIONS + code-review enforced, NOT a brittle engine param-name blocklist. The former
# test_forbidden_param_field_raises / test_forbidden_time_exit_param_raises /
# test_phase3_days_is_not_forbidden tested that removed scan — deleted with it. validate_invariants
# now only enforces the structural explicit-exposure invariant (adds → portfolio_risk).


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


def test_filter_not_required_under_y() -> None:
    # Y (Falk): "filter" is NO LONGER a required phase — the champion applies its floors at the
    # selection gate (lean_entry._coarse_selection), not a per-bar filter phase. A config with
    # universe/signal/sizing and NO filter must be ACCEPTED. "filter" stays a known kind (in
    # PHASE_ORDER) so a future strategy MAY still add a real per-bar filter phase.
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


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
