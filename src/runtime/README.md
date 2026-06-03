# src/runtime

The LEAN runtime layer — code that executes inside the QC algorithm (bundled into the dist by
cloud_package's src AST-walk).

Goes here: `lean_entry.py` (the QCAlgorithm subclass — universe/decision/intraday clocks, indicator
lifecycle), `lean_indicators.py` (LEAN-faithful Ichimoku/ADX/SMA/WeeklyIchimokuAsOf ports), the
warmup-cache READ side (`warmup_weekly_cache.py` — key formula + ObjectStore load, #358), cost model,
tag schema. Does not go here: offline/runner mechanics (those live in `sweeps/` + `scripts/`, NOT
bundled), phase implementations (`src/phases/`), or the engine core (`src/engine/`).

Bundling rule (#358): runtime-READ code lives here (dist-bundled); offline-WRITE/build code lives in
`scripts/`/`sweeps/`; a shared key formula lives here so write==read from one source.
