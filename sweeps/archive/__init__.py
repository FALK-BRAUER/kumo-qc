"""Results-archive snapshotter (#276b / results-archive-design.md).

The DURABLE per-run writer — the one channel that survives the cloud BT purge. After every
backtest (local or cloud) completes and `assert_cloud_clean` passes, the caller invokes
`persist_run(...)` to write `results/archive/<config_hash>/<backtest_id>/` containing the full
config + provenance + ALL QC statistics (`result.json`) and one closed trade per line with its
decision context parsed from the entry order TAG (`trades.jsonl.gz`).

This is the #1-RISK component: a single point of total data loss. It is FAIL-LOUD by contract —
any API error, parse failure, bad status, or the silent-miss (empty trades when Total Orders > 0)
RAISES rather than writing a silent partial.

Public surface:
  - persist_run(...)                  — the durable per-run writer
  - RunStatus                         — the 3-state {COMPLETED_CLEAN, COMPLETED_DEGRADED, CRASHED}
  - ArchiveError + subclasses         — fail-loud failure modes
  - TRADE_SCHEMA / TRADE_SCHEMA_VERSION — the trades.jsonl line schema (the doc + drift guard)
  - OrdersFetch                       — the injected `/orders/read` callable Protocol
"""
from __future__ import annotations

from sweeps.archive.snapshot import (
    ArchiveError,
    CENSORED_EXIT_REASON,
    EmptyTradesError,
    M2M_LOCAL_PARQUET,
    M2M_QC_NATIVE,
    M2M_UNAVAILABLE,
    M2MMark,
    OrdersFetch,
    OrdersFetchError,
    RunStatus,
    SchemaValidationError,
    TRADE_SCHEMA,
    TRADE_SCHEMA_VERSION,
    persist_run,
)

__all__ = [
    "ArchiveError",
    "CENSORED_EXIT_REASON",
    "EmptyTradesError",
    "M2M_LOCAL_PARQUET",
    "M2M_QC_NATIVE",
    "M2M_UNAVAILABLE",
    "M2MMark",
    "OrdersFetch",
    "OrdersFetchError",
    "RunStatus",
    "SchemaValidationError",
    "TRADE_SCHEMA",
    "TRADE_SCHEMA_VERSION",
    "persist_run",
]
