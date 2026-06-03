# tests/runtime

Unit tests for the runtime layer (`src/runtime/`) — the QCAlgorithm entry (`lean_entry`), the
LEAN-faithful indicator ports (`lean_indicators`), and the warmup-cache read side
(`warmup_weekly_cache`).

Goes here: tests exercising runtime mechanics with light stubs (the QC base is `object` outside LEAN)
— e.g. the #358 weekly-cache consumption hook (cache-or-replay, fail-closed, lazy per-symbol memo,
engagement log). Does not go here: phase/engine tests (`tests/engine`, `tests/phases`), sweep-runner
tests (`tests/sweeps`), or anything needing a live LEAN backtest.
