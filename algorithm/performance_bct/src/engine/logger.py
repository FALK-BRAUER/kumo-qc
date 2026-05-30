from __future__ import annotations
import json
from typing import Any
from engine.base import PhaseResult


class ComponentLogger:
    def __init__(self, qc: Any):
        self._qc = qc

    def log_phase(self, kind: str, phase: Any, result: PhaseResult) -> None:
        facts_str = json.dumps(result.facts, separators=(",", ":"))
        metrics_str = json.dumps(result.metrics, separators=(",", ":"))
        self._qc.Log(
            f"PHASE|{kind}|{phase.version_marker}|"
            f"blocked={result.blocked}|reason={result.reason}|"
            f"facts={facts_str}|metrics={metrics_str}"
        )
        if result.blocked:
            self._qc.Log(f"BLOCK|{kind}|{phase.version_marker}|reason={result.reason}")

    def log_tick(self, chain: list[str], entries: int, exits: int, adds: int) -> None:
        self._qc.Log(f"STRATEGY_TICK|chain={','.join(chain)}|entries={entries}|exits={exits}|adds={adds}")

    def log_strategy_init(self, config_hash: str, name: str, version: str) -> None:
        self._qc.Log(f"STRATEGY_INIT|hash={config_hash}|name={name}|version={version}")
