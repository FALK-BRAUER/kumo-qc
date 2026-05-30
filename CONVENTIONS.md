# CONVENTIONS — kumo-qc

The rules every contribution conforms to. The PR gate enforces these. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the structure.

## Type safety
- **`mypy --strict` (and pyright strict) must pass on `src/`.** No `Any` leakage, no untyped defs.
- **Phase interface = `typing.Protocol`** (`@runtime_checkable`). Optionally subclass a `BasePhase` ABC for shared helpers, but the engine/config depend on the Protocol.
- **Per-phase params = a nested `.Params` dataclass** on the phase class. Never `dict[str, Any]`.
- **Hot per-bar objects** (`BarState`, `PhaseResult`, intents) = `dataclass(slots=True)`.

## Config
- **Strategies hold DIRECT CLASS REFERENCES**, not strings: `Slot(impl=SomePhase, params=SomePhase.Params(...))`. No runtime registry for wiring (a registry may exist only as a sweep discovery catalog).
- One **ACTIVE** strategy per build (`main.py`). Rebuild + redeploy to switch.

## Phases (library members)
- Live in `src/phases/<kind>/<impl>/<impl>.py` with a mirror test in `tests/phases/<kind>/<impl>/`.
- **No phase reads files via relative paths.** All external assets are injected through typed params. (Otherwise the closure packager misses them and cloud breaks.)
- Each phase declares `PHASE_KIND`, `REQUIRES_UPSTREAM`, `PROVIDES_DOWNSTREAM`, a `version_marker`, and a mandatory file header (tested params + setup + charter + changelog).
- **Merge a phase when it is correct** (tests + parity + charter + header pass) — independent of whether it improves the champion.

## Charter invariants (engine refuses to start otherwise)
- **No count caps** (`max_positions`, `max_lots`, `max_adds`, `max_pyramid_lots`, `max_slots`, ...). Bound exposure with `gross_exposure_cap` (a % rule), never a count.
- **No time-based exits** (`max_hold_days`, `exit_after_days`, ...).
- **Explicit exposure only** — if `adds` is enabled, `gross_exposure_cap` MUST be enabled.
- **NO fixed / snapshot universe — anywhere.** No 326, no hardcoded ticker list, in code, config, data, or tests. Universe = **dynamic, point-in-time** only. The fixed snapshot was the root of the slot-tiebreak / data-divergence / parity-chasing time-sinks and **proved nothing** — eradicated. Which tickers a strategy selects = the dynamic universe phase, pinned by config-hash; the substrate (the zip set) is fingerprinted separately.

## Parity (cloud vs local)
- Goal = **short-timeframe REPRODUCIBILITY, to a reasonable extent**: local == cloud on a SHORT window (days), same code (`dist/`) + same substrate (fingerprint), within tolerance.
- **NOT** full-FY exact-match — the cloud-vs-local data-vendor residual is a known irreducible; chasing it is a rabbit-hole (cloud = ground-truth).
- **NOT** parity against a fixed-universe oracle (326 proved nothing).
- Refactor-correctness is a SEPARATE check: per-phase, universe-agnostic golden-master (v2 phase logic == monolith logic on a sample of tickers) — not an end-to-end fixed-universe parity.

## Build / deploy / dist
- LEAN runs the **`dist/`** artifact — both local and cloud. No `if cloud:` branch in strategy code.
- `dist/` is **generated + git-tracked + NOT linted** (mypy excludes it). Never hand-edit it.
- The build (`build/cloud_package.py`) packages ONLY the active config's phase closure, and is itself unit-tested.
- Every result is pinned to **(git commit + config-hash + data-fingerprint)** via `dist/_metadata.py`, logged on startup. No result without that pinning enters `results/bt-results.csv`.

## Data (local backtest substrate)
- `data/` = RAW daily OHLCV only, built from Massive SIP parquet (`scripts/build_daily_from_parquet.py`). **Never back-adjusted, never mixed** (adjusted corrupts Ichimoku — the 7x-calibration lesson).
- Zips are gitignored; `data/MANIFEST.json` (the **data fingerprint**) + `data/README.md` are tracked.
- **Every result pins to the data fingerprint** (carried in `dist/_metadata.py`). Local and cloud must run the same data state — verify the fingerprint before trusting parity.

## Git workflow
- **Rebase, never merge-commit.** Linear history. Rebase a feature branch onto latest `main`, then `--ff-only` merge.
- One feature branch = one worktree. **Delete the branch + worktree after integration.**
- **Push immediately** after every clean commit (the 2026-05-23 unpushed-loss lesson).
- Conventional Commits.

## Testing
- `tests/` **mirrors `src/`** 1:1 (`tests/<path>/test_<mod>.py`). Shared primitives in `tests/harness/`, cross-cutting in `tests/integration/`.
- Parity tests run the built **`dist/`**, not `src/`.

## Anti-drift
- **Every non-hidden directory has a `README.md`** (3-5 lines: what it holds / what goes here / what doesn't). Create/update it when you touch a directory. This is how the structure stays honest.
