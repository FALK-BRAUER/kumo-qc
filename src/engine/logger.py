"""Structured JSON-lines logger.

Ports v1 arch-a ComponentLogger. JSON-lines (not pipe-delimited) so parity_diff
parses deterministically even when facts contain '|' or ','. Adds log_phase_loaded
(per-phase marker at init — observability of which code loaded).
"""
from __future__ import annotations

import json
from typing import Any

from engine.base import PhaseResult


class ComponentLogger:
    def __init__(self, qc: Any) -> None:
        self._qc = qc

    def log_phase(self, kind: str, phase: Any, result: PhaseResult) -> None:
        if getattr(self._qc, "LOG_ONLY_ACTIVE_PHASES", False) and not self._is_active_result(result):
            return
        metrics = result.metrics if getattr(self._qc, "LOG_PHASE_METRICS", True) else {}
        self._qc.Log(json.dumps({
            "evt": "PHASE",
            "kind": kind,
            "marker": phase.version_marker,
            "blocked": result.blocked,
            "reason": result.reason,
            "facts": result.facts,
            "metrics": metrics,
        }, separators=(",", ":")))
        if result.blocked:
            self._qc.Log(json.dumps({
                "evt": "BLOCK", "kind": kind,
                "marker": phase.version_marker, "reason": result.reason,
            }, separators=(",", ":")))

    def log_tick(self, chain: list[str], entries: int, exits: int, adds: int) -> None:
        if getattr(self._qc, "LOG_TICK_EVENTS", True) is False and entries == 0 and exits == 0 and adds == 0:
            return
        self._qc.Log(json.dumps({
            "evt": "STRATEGY_TICK", "chain": chain,
            "entries": entries, "exits": exits, "adds": adds,
        }, separators=(",", ":")))

    def log_strategy_init(self, config_hash: str, name: str, version: str) -> None:
        self._qc.Log(json.dumps({
            "evt": "STRATEGY_INIT", "hash": config_hash, "name": name, "version": version,
        }, separators=(",", ":")))

    def log_phase_loaded(self, kind: str, marker: str) -> None:
        self._qc.Log(json.dumps({
            "evt": "PHASE_LOADED", "kind": kind, "marker": marker,
        }, separators=(",", ":")))

    def _is_active_result(self, result: PhaseResult) -> bool:
        if result.blocked:
            return True
        if getattr(self._qc, "LOG_PHASE_DECISIONS_ACTIVE", True):
            decision = result.decision
            if isinstance(decision, (list, tuple, set, dict)) and len(decision) > 0:
                return True
        active_fact_keys = {
            "exit_count",
            "target_count",
            "giveback_count",
            "no_progress_count",
            "roundtrip_count",
            "capped_loss_count",
            "filled",
            "fired",
            "stamped",
            "updated",
        }
        for key in active_fact_keys:
            value = result.facts.get(key)
            if isinstance(value, bool):
                if value:
                    return True
            elif isinstance(value, (int, float)) and value > 0:
                return True
        return False
