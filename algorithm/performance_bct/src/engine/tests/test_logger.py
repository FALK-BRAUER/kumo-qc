from engine.logger import ComponentLogger
from engine.base import PhaseResult


class FakeQC:
    def __init__(self):
        self.logged = []

    def Log(self, msg: str):
        self.logged.append(msg)


def make_result(decision=None, blocked=False, reason="ok", facts=None, metrics=None):
    return PhaseResult(decision=decision, blocked=blocked, reason=reason, facts=facts or {}, metrics=metrics or {})


import json as _json


def test_logger_emits_phase_json():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = make_result(facts={"score": 8})

    class FakePhase:
        version_marker = "bct_score_v1"

    logger.log_phase("signal", FakePhase(), result)
    assert len(qc.logged) == 1
    record = _json.loads(qc.logged[0])
    assert record["evt"] == "PHASE"
    assert record["kind"] == "signal"
    assert record["marker"] == "bct_score_v1"
    assert record["facts"]["score"] == 8


def test_logger_emits_block_json_when_blocked():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = make_result(blocked=True, reason="VIX above threshold")

    class FakePhase:
        version_marker = "vix_threshold_v1"

    logger.log_phase("regime", FakePhase(), result)
    records = [_json.loads(l) for l in qc.logged]
    block = next(r for r in records if r["evt"] == "BLOCK")
    assert block["reason"] == "VIX above threshold"


def test_logger_emits_tick_json():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_tick(chain=["regime", "signal"], entries=2, exits=1, adds=0)
    record = _json.loads(qc.logged[0])
    assert record["evt"] == "STRATEGY_TICK"
    assert record["entries"] == 2
    assert record["exits"] == 1


def test_logger_emits_strategy_init_json():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_strategy_init(config_hash="abc123", name="baseline-v1", version="1.0.0")
    record = _json.loads(qc.logged[0])
    assert record["evt"] == "STRATEGY_INIT"
    assert record["hash"] == "abc123"


def test_logger_phase_json_round_trips_facts_with_special_chars():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = make_result(facts={"reason": "close|below|kijun", "val": 1.5})

    class FakePhase:
        version_marker = "trail_v1"

    logger.log_phase("trail", FakePhase(), result)
    record = _json.loads(qc.logged[0])
    assert record["facts"]["reason"] == "close|below|kijun"
