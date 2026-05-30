import pytest
from engine.base import PhaseInterface, PhaseResult, CharterViolation, UniverseLoadError
from engine.context import PhaseContext, BarState
from datetime import datetime


class ConcretePhase(PhaseInterface):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = ["ranked_candidates"]

    def __init__(self, params: dict, logger):
        self._params = params
        self._logger = logger

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(decision=[], blocked=False, reason="ok", facts={}, metrics={})

    @property
    def version_marker(self) -> str:
        return "stub_signal_v1"


class MissingEvaluatePhase(PhaseInterface):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = []

    def __init__(self, params, logger):
        self._params = params
        self._logger = logger

    @property
    def version_marker(self):
        return "v1"


def make_ctx():
    class FakeQC:
        pass
    return PhaseContext(qc=FakeQC(), time=datetime(2025, 1, 2), data=None)


def test_phase_result_fields():
    r = PhaseResult(decision="buy", blocked=False, reason="signal ok", facts={"score": 8}, metrics={"count": 1})
    assert r.decision == "buy"
    assert not r.blocked
    assert r.facts["score"] == 8


def test_concrete_phase_implements_interface():
    phase = ConcretePhase(params={"min_score": 7}, logger=None)
    assert phase.PHASE_KIND == "signal"
    assert phase.version_marker == "stub_signal_v1"


def test_enabled_defaults_true():
    phase = ConcretePhase(params={}, logger=None)
    assert phase.enabled is True


def test_enabled_false_when_param_set():
    phase = ConcretePhase(params={"enabled": False}, logger=None)
    assert phase.enabled is False


def test_evaluate_returns_phase_result():
    phase = ConcretePhase(params={}, logger=None)
    result = phase.evaluate(make_ctx())
    assert isinstance(result, PhaseResult)
    assert result.blocked is False


def test_missing_evaluate_raises_on_instantiation():
    with pytest.raises(TypeError):
        MissingEvaluatePhase(params={}, logger=None)


def test_charter_violation_is_exception():
    with pytest.raises(CharterViolation):
        raise CharterViolation("max_positions is a count cap")


def test_universe_load_error_is_exception():
    with pytest.raises(UniverseLoadError):
        raise UniverseLoadError("universe empty — engine refuses to start")


def test_validate_config_default_passes():
    phase = ConcretePhase(params={"min_score": 7}, logger=None)
    phase.validate_config({"min_score": 7})  # should not raise
