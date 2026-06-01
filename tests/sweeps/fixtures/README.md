# tests/sweeps/fixtures/

Captured/synthetic result documents for the #214 adapter tests — ZERO real LEAN / cloud spend.

- `lean_result_*.json` — local `lean backtest` result-JSON shapes (clean / degraded-0-orders /
  NaN-metric) for `LocalLeanRun` + the shared parser.
- `cloud_read_*.json` — QC `/backtests/read` document shapes (clean / crashed / partial /
  null-orders) for `CloudLeanRun` + `assert_cloud_clean`.

What goes here: small, hand-checkable result fixtures used by `test_result_parse` /
`test_local_lean` / `test_cloud_lean`. What doesn't: real backtest output (gitignored), live
API captures with secrets, or anything large.
