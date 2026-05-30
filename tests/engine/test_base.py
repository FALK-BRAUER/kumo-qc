from datetime import datetime

from engine.base import BasePhase, PhaseInterface, PhaseResult
from engine.context import PhaseContext


class _Concrete(BasePhase):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    def __init__(self, enabled: bool = True) -> None:
        from dataclasses import make_dataclass
        params = type("P", (), {"enabled": enabled})()
        super().__init__(params, None)

    @property
    def version_marker(self) -> str:
        return "concrete_v1"

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(decision=None, blocked=False, reason="ok", facts={}, metrics={})


def test_phase_result_slots() -> None:
    r = PhaseResult(decision="buy", blocked=False, reason="x", facts={"s": 8}, metrics={})
    assert r.facts["s"] == 8


def test_runtime_checkable_protocol() -> None:
    # The fixed-blocker test: enabled-from-params + structural Protocol satisfaction.
    phase = _Concrete(enabled=True)
    assert isinstance(phase, PhaseInterface)
    assert phase.enabled is True
    assert _Concrete(enabled=False).enabled is False


def test_non_phase_fails_protocol() -> None:
    assert not isinstance(object(), PhaseInterface)
