from __future__ import annotations
import json
from typing import Any
from engine.base import PhaseResult


class ComponentLogger:
    def __init__(self, qc: Any):
        self._qc = qc

    def log_phase(self, kind: str, phase: Any, result: PhaseResult) -> None:
        # JSON-lines for machine-parsed parity-critical records (no | in values)
        record = {
            "evt": "PHASE",
            "kind": kind,
            "marker": phase.version_marker,
            "blocked": result.blocked,
            "reason": result.reason,
            "facts": result.facts,
            "metrics": result.metrics,
        }
        self._qc.Log(json.dumps(record, separators=(",", ":")))
        if result.blocked:
            self._qc.Log(json.dumps({
                "evt": "BLOCK",
                "kind": kind,
                "marker": phase.version_marker,
                "reason": result.reason,
            }, separators=(",", ":")))

    def log_tick(self, chain: list[str], entries: int, exits: int, adds: int) -> None:
        self._qc.Log(json.dumps({
            "evt": "STRATEGY_TICK",
            "chain": chain,
            "entries": entries,
            "exits": exits,
            "adds": adds,
        }, separators=(",", ":")))

    def log_phase_loaded(self, kind: str, module: str, marker: str) -> None:
        self._qc.Log(json.dumps({
            "evt": "PHASE_LOADED",
            "kind": kind,
            "module": module,
            "marker": marker,
        }, separators=(",", ":")))

    def log_strategy_init(self, config_hash: str, name: str, version: str) -> None:
        self._qc.Log(json.dumps({
            "evt": "STRATEGY_INIT",
            "hash": config_hash,
            "name": name,
            "version": version,
        }, separators=(",", ":")))
