# data/

The clean local LEAN backtest data directory. **RAW daily OHLCV only.** Single source of truth for what local backtests read; must mirror what cloud reads.

## What it holds
- `equity/usa/daily/<ticker>.zip` — LEAN-format daily bars. **GITIGNORED** (bulky, regenerable). The full substrate (~19k tickers), NOT a fixed subset.
- `MANIFEST.json` — **TRACKED**, the **SUBSTRATE fingerprint** (hash of the zip SET — "what data exists"). Generated at #220 when the substrate scope is defined. **NOT a universe-subset** — universe selection is a strategy/phase concern (dynamic), pinned separately by config-hash. (A prior 326-ticker manifest was removed — it conflated substrate with a fixed universe; see #219.)
- `README.md` — this file. TRACKED.

## NO fixed universe (hard rule)
There is **no 326 / fixed / snapshot universe anywhere** — in this dir, in code, in config. The fixed snapshot was the root of the slot-tiebreak / data-divergence / parity-chasing time-sinks. Universe = **dynamic, point-in-time** only (#220). This dir fingerprints the SUBSTRATE; which tickers a strategy selects is the dynamic universe phase, never a stored list here.

## Provenance (non-negotiable)
- Built from **Massive SIP `day_aggs` / 5-min parquet** (`kumo data build-daily`), **RAW / unadjusted**.
- **NEVER back-adjusted.** Adjusted prices corrupt Ichimoku + ATR (the 7x-calibration / oracle-1.079-artifact lesson). Raw only.
- **NEVER mixed** (all-raw or rebuild — never some-raw-some-adjusted; mixed = silently wrong).

## Workflow — the `kumo data` subcommands (#221)
The substrate is built + fingerprinted via the operator CLI (`kumo`, in `cli/`), which wraps
the data keepers verbatim:
```bash
# fast default (stat-only signature: sorted ticker+file_size; detects add/remove/resize):
kumo data manifest
# byte-exact (sha256 of every zip; minutes-scale over ~19k files) before a parity claim:
kumo data manifest --mode sha256
```
`mode` is recorded in the manifest so a reader knows the guarantee level. mtime is
deliberately EXCLUDED (not reproducible across checkout/rsync → would break determinism).
Whenever you rebuild zips from parquet (`kumo data build-daily`), re-run this and commit
the new `MANIFEST.json`. Other data commands: `kumo data conform-coarse` (local
coarse-fundamental CSVs), `kumo data etf-universe`, `kumo data extend`.

The **dynamic universe** (which tickers a strategy selects, point-in-time) is **NOT** built
by a `build_universe.py` precompute — that script was removed. Universe selection is now a
**live, point-in-time** concern: `src/runtime/lean_entry.py::_coarse_selection` filters the
coarse feed at runtime (identical code path local + cloud). No stored ticker list lives here.

## Rules
- Never hand-edit zips. Rebuild from parquet → re-fingerprint the SUBSTRATE → bump `MANIFEST.json`.
- **Every result pins to (substrate-fingerprint + config-hash)** via `dist/_metadata.py`. A result not pinned is not valid (CONVENTIONS.md).
- Local and cloud must run the SAME substrate — verify the fingerprint before trusting parity.

## Does NOT hold
- Backtest OUTPUT (`backtests/`, gitignored). Adjusted data, vendor caches, SQLite (`*.db`). **Any fixed-universe ticker list.**
