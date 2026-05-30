from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext


class StubPhase(PhaseInterface):
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    def __init__(self, kind: str, blocked: bool = False, params: dict = None, logger=None):
        super().__init__(params=params or {}, logger=logger)
        self.PHASE_KIND = kind
        self._blocked = blocked
        self.called = False

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        self.called = True
        return PhaseResult(decision=None, blocked=self._blocked, reason="stub", facts={}, metrics={})

    @property
    def version_marker(self) -> str:
        return f"stub_{self.PHASE_KIND}_v1"


def make_stub(kind: str, blocked: bool = False) -> StubPhase:
    return StubPhase(kind=kind, blocked=blocked)
