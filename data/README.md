# data/

The clean local LEAN backtest data directory. **RAW daily OHLCV only.** Single source of truth for what local backtests read; must mirror what cloud reads.

## What it holds
- `equity/usa/daily/<ticker>.zip` — LEAN-format daily bars. **GITIGNORED** (bulky, regenerable).
- `MANIFEST.json` — **TRACKED**. Per-file sha256 = the **data fingerprint** that pins every result. (Current FY2025 raw substrate: `ba8307b6e556cca4`.)
- `README.md` — this file. TRACKED.

## Provenance (non-negotiable)
- Built from **Massive SIP `day_aggs` / 5-min parquet** (`scripts/build_daily_from_parquet.py`), **RAW / unadjusted**.
- **NEVER back-adjusted.** Adjusted prices corrupt Ichimoku + ATR (the 7x-calibration / oracle-1.079-artifact lesson). Raw only.
- **NEVER mixed** (all-raw or rebuild — never some-raw-some-adjusted; mixed = silently wrong).

## Rules
- Never hand-edit zips. Rebuild from parquet → re-fingerprint → bump `MANIFEST.json`.
- **Every result pins to the fingerprint** (`dist/_metadata.py` carries it). A result not pinned to its data fingerprint is not valid (CONVENTIONS.md).
- Local and cloud must run the SAME data state — verify the fingerprint matches before trusting a parity result.

## Does NOT hold
- Backtest OUTPUT (that's `backtests/`, gitignored).
- Adjusted data, vendor caches, SQLite (`*.db`).
