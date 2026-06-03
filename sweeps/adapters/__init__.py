"""Real RunConfig adapters (#214) — the run-a-config primitive behind the Protocol.

`sweeps/` mechanics (pool/leaderboard/provenance) NEVER call LEAN or the cloud directly;
they call the injected `RunConfig` Protocol. Unit tests inject a deterministic mock (ZERO
spend). These adapters are the REAL impls of that seam:

  - `LocalLeanRun`  — drives `lean backtest` in an isolated project dir, parses the result
                      JSON, marker-verifies, fails loud on degraded data. The fast filter.
  - `CloudLeanRun`  — drives `scripts/qc_v2_cloud` deploy+run, gates on `assert_cloud_clean`,
                      parses the cloud statistics. Ground truth.

Both satisfy the RunConfig Protocol (`__call__ -> ResultMetrics`) AND the richer
RichRunConfig (`run_result -> RunResult`) for the #323 objective layer — ONE parse, two
views (see the design delta in types.py). They are integration-flagged: the unit tests
here exercise them against FIXTURE result dirs / MOCKED cloud responses, never real spend.
"""
from __future__ import annotations

from sweeps.adapters.cloud_lean import CloudLeanRun, assert_cloud_clean
from sweeps.adapters.local_lean import LocalLeanRun
from sweeps.adapters.result_parse import (
    parse_daily_returns,
    parse_metrics,
    parse_run_result,
    parse_trades,
)

__all__ = [
    "CloudLeanRun",
    "LocalLeanRun",
    "assert_cloud_clean",
    "parse_daily_returns",
    "parse_metrics",
    "parse_run_result",
    "parse_trades",
]
