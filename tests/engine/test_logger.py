"""Behavioral coverage for engine.logger.ComponentLogger.

#246 [B2]: logger.py had NO test. ComponentLogger emits structured JSON-lines via qc.Log().
These drive a FAKE qc that captures every Log() call, then PARSE each captured line as JSON
(proving it is valid JSON-lines) and assert the event type + field contents. Key behavior:
log_phase emits ONE PHASE record normally, and an ADDITIONAL BLOCK record when the result is
blocked (src ~:29-33). Edge cases: empty facts/metrics, and the blocked-result two-line emit.
"""
from __future__ import annotations

import json
from typing import Any

from engine.base import PhaseResult
from engine.logger import ComponentLogger


class FakeQC:
    """Captures every Log() call so we can parse the emitted JSON-lines."""

    def __init__(self) -> None:
        self.logged: list[str] = []

    def Log(self, msg: str) -> None:
        self.logged.append(msg)


class FakePhase:
    """Minimal phase exposing the one attribute the logger reads: version_marker."""

    def __init__(self, marker: str) -> None:
        self.version_marker = marker


def _records(qc: FakeQC) -> list[dict[str, Any]]:
    """Parse every captured Log line as JSON — fails loudly if any line is not valid JSON."""
    return [json.loads(line) for line in qc.logged]


# ------------------------------------------------------------------ log_phase (unblocked)


def test_log_phase_emits_single_valid_json_phase_record() -> None:
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = PhaseResult(
        decision="GO", blocked=False, reason="ok",
        facts={"price": 101.5, "ticker": "AAPL"}, metrics={"score": 8},
    )
    logger.log_phase("signal", FakePhase("bct_v1"), result)

    assert len(qc.logged) == 1  # unblocked -> exactly one line, no BLOCK
    (rec,) = _records(qc)
    assert rec["evt"] == "PHASE"
    assert rec["kind"] == "signal"
    assert rec["marker"] == "bct_v1"
    assert rec["blocked"] is False
    assert rec["reason"] == "ok"
    assert rec["facts"] == {"price": 101.5, "ticker": "AAPL"}
    assert rec["metrics"] == {"score": 8}


def test_log_phase_empty_facts_and_metrics() -> None:
    """Edge: a result with empty facts/metrics still emits a valid PHASE record."""
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = PhaseResult(decision=None, blocked=False, reason="", facts={}, metrics={})
    logger.log_phase("filter", FakePhase("flt_v1"), result)

    (rec,) = _records(qc)
    assert rec["evt"] == "PHASE"
    assert rec["facts"] == {}
    assert rec["metrics"] == {}
    assert rec["reason"] == ""


# -------------------------------------------------------------------- log_phase (blocked)


def test_log_phase_blocked_emits_phase_then_block() -> None:
    """src ~:29-33 — when result.blocked, a SECOND BLOCK record is emitted after PHASE."""
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = PhaseResult(
        decision=None, blocked=True, reason="below floor",
        facts={"price": 1.0}, metrics={},
    )
    logger.log_phase("filter", FakePhase("flt_v1"), result)

    assert len(qc.logged) == 2  # blocked -> PHASE + BLOCK
    phase_rec, block_rec = _records(qc)
    assert phase_rec["evt"] == "PHASE"
    assert phase_rec["blocked"] is True
    assert block_rec["evt"] == "BLOCK"
    assert block_rec["kind"] == "filter"
    assert block_rec["marker"] == "flt_v1"
    assert block_rec["reason"] == "below floor"


# ------------------------------------------------------------------------------- log_tick


def test_log_tick_emits_strategy_tick_record() -> None:
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_tick(chain=["filter", "signal", "sizing"], entries=2, exits=1, adds=0)

    (rec,) = _records(qc)
    assert rec["evt"] == "STRATEGY_TICK"
    assert rec["chain"] == ["filter", "signal", "sizing"]
    assert rec["entries"] == 2
    assert rec["exits"] == 1
    assert rec["adds"] == 0


def test_log_tick_empty_chain() -> None:
    """Edge: an empty chain / all-zero counts still emit a valid record."""
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_tick(chain=[], entries=0, exits=0, adds=0)

    (rec,) = _records(qc)
    assert rec["evt"] == "STRATEGY_TICK"
    assert rec["chain"] == []


def test_log_only_active_phases_suppresses_noop_phase() -> None:
    qc = FakeQC()
    qc.LOG_ONLY_ACTIVE_PHASES = True
    logger = ComponentLogger(qc)

    logger.log_phase(
        "entry_trigger",
        FakePhase("stub_entry_trigger_v1"),
        PhaseResult(
            decision=[],
            blocked=False,
            reason="no fire",
            facts={"fired": 0, "armed": 18},
            metrics={},
        ),
    )

    assert qc.logged == []


def test_log_only_active_phases_keeps_active_phase() -> None:
    qc = FakeQC()
    qc.LOG_ONLY_ACTIVE_PHASES = True
    logger = ComponentLogger(qc)

    logger.log_phase(
        "exit_hard",
        FakePhase("scratch_flat_exit_v1"),
        PhaseResult(
            decision=[],
            blocked=False,
            reason="2 scratch-flat exits",
            facts={"exit_count": 2},
            metrics={},
        ),
    )

    (rec,) = _records(qc)
    assert rec["evt"] == "PHASE"
    assert rec["facts"] == {"exit_count": 2}


def test_log_tick_events_false_suppresses_noop_tick_but_keeps_active_tick() -> None:
    qc = FakeQC()
    qc.LOG_TICK_EVENTS = False
    logger = ComponentLogger(qc)

    logger.log_tick(chain=["entry_trigger"], entries=0, exits=0, adds=0)
    logger.log_tick(chain=["entry_trigger"], entries=1, exits=0, adds=0)

    (rec,) = _records(qc)
    assert rec["evt"] == "STRATEGY_TICK"
    assert rec["entries"] == 1


# ------------------------------------------------------------------------ log_strategy_init


def test_log_strategy_init_emits_init_record() -> None:
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_strategy_init(config_hash="abc123def456", name="champ", version="3.1.4")

    (rec,) = _records(qc)
    assert rec["evt"] == "STRATEGY_INIT"
    assert rec["hash"] == "abc123def456"
    assert rec["name"] == "champ"
    assert rec["version"] == "3.1.4"


# ------------------------------------------------------------------------ log_phase_loaded


def test_log_phase_loaded_emits_phase_loaded_record() -> None:
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_phase_loaded(kind="universe", marker="dv_rank_cap_v1")

    (rec,) = _records(qc)
    assert rec["evt"] == "PHASE_LOADED"
    assert rec["kind"] == "universe"
    assert rec["marker"] == "dv_rank_cap_v1"


# --------------------------------------------------- JSON-lines integrity across a session


def test_all_emitted_lines_are_independent_json_lines() -> None:
    """Every Log() emission is ONE self-contained JSON object (newline-delimitable),
    so parity_diff can parse line-by-line even when facts contain '|' or ','."""
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_strategy_init("h", "n", "v")
    logger.log_phase_loaded("filter", "flt_v1")
    logger.log_phase(
        "filter", FakePhase("flt_v1"),
        PhaseResult(decision=None, blocked=True, reason="r|with,delims", facts={"a|b": "c,d"}, metrics={}),
    )
    logger.log_tick(["filter"], 0, 0, 0)

    # init + loaded + (PHASE + BLOCK) + tick = 5 lines, each parseable, no embedded newlines.
    assert len(qc.logged) == 5
    for line in qc.logged:
        assert "\n" not in line
        json.loads(line)
    # the delimiter-laden facts round-trip intact through JSON (the whole point of JSON-lines).
    phase_rec = json.loads(qc.logged[2])
    assert phase_rec["facts"] == {"a|b": "c,d"}
    assert phase_rec["reason"] == "r|with,delims"
