from engine.logger import ComponentLogger
from engine.base import PhaseResult


class FakeQC:
    def __init__(self):
        self.logged = []

    def Log(self, msg: str):
        self.logged.append(msg)


def make_result(decision=None, blocked=False, reason="ok", facts=None, metrics=None):
    return PhaseResult(decision=decision, blocked=blocked, reason=reason, facts=facts or {}, metrics=metrics or {})


def test_logger_emits_phase_line():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = make_result(facts={"score": 8})

    class FakePhase:
        version_marker = "bct_score_v1"

    logger.log_phase("signal", FakePhase(), result)
    assert len(qc.logged) == 1
    line = qc.logged[0]
    assert line.startswith("PHASE|signal|")
    assert "bct_score_v1" in line
    assert "score" in line


def test_logger_emits_block_line_when_blocked():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = make_result(blocked=True, reason="VIX above threshold")

    class FakePhase:
        version_marker = "vix_threshold_v1"

    logger.log_phase("regime", FakePhase(), result)
    assert any("BLOCK" in line for line in qc.logged)
    assert any("VIX above threshold" in line for line in qc.logged)


def test_logger_emits_tick_summary():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_tick(chain=["regime", "signal"], entries=2, exits=1, adds=0)
    assert len(qc.logged) == 1
    line = qc.logged[0]
    assert line.startswith("STRATEGY_TICK|")
    assert "entries=2" in line
    assert "exits=1" in line


def test_logger_emits_strategy_init():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_strategy_init(config_hash="abc123", name="baseline-v1", version="1.0.0")
    assert len(qc.logged) == 1
    assert "STRATEGY_INIT" in qc.logged[0]
    assert "abc123" in qc.logged[0]
