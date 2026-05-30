# kumo-qc Architecture v2 — Type-Safe Phase Library

**Status:** Canonical charter (2026-05-30, Falk). Supersedes v1 (`algorithm/performance_bct` layout).
**Epic:** #208. **Conventions:** [CONVENTIONS.md](../CONVENTIONS.md).
**Owner:** fintrack HQ (structure + verification) + kumo-qc orchestrator (code + BTs).

The repo root IS the strategy project. A strategy = a typed `STRATEGY_CONFIG` selecting composable **phase** plugins from a library, run by one engine in a fixed `PHASE_ORDER`. Built to a flat `dist/` that LEAN runs both locally and on cloud.

---

## 1. Core principles
1. **Phase decomposition** — a strategy is a composition of discrete phases (universe → signal → regime → ranking → entry → sizing → stops → trail → exits → adds → ...). ~29 kinds; a strategy uses a subset.
2. **Repo-root-as-project** — `src/ tests/ build/ dist/` at root. No `algorithm/<name>/` nesting.
3. **Phase library** — `src/phases/<kind>/<impl>/` accumulates every merged, useful phase. Config switches them on/off. Merge criterion = phase *correctness*, not champion status.
4. **Typed, direct-reference config** — `src/strategies/<name>.py` holds a `StrategyConfig` of `Slot(impl=SomePhase, params=SomePhase.Params(...))` — **direct class references, no runtime registry, no stringly dicts**. `mypy --strict` validates config→class→params.
5. **One active strategy** deployed at a time; rebuild + redeploy to switch.
6. **Config-aware flat build** — `build/cloud_package.py` AST-parses the active config's import closure and flattens ONLY the enabled phases to `dist/`. QC cloud has no subdirectories.
7. **Parity by construction** — LEAN runs the SAME `dist/` locally and on cloud. The harness emulates cloud; there is no `if cloud:` branch in strategy code.
8. **Provenance pinning** — every result is pinned to (code commit + config hash + **data fingerprint**). A result not pinned to its data state is not trusted (the 1.079 lesson).

## 2. Type-safety model (see CONVENTIONS.md for rules)
- **Phase interface = `typing.Protocol`** (structural) + optional `BasePhase` ABC for shared helpers. `@runtime_checkable` for validating built phases.
- **Hot per-bar objects** (`BarState`, `PhaseResult`) = `dataclass(slots=True)`.
- **Per-phase `.Params`** = a nested typed dataclass (never `dict[str, Any]`).
- **Type-check `src/` only.** `dist/` is a generated artifact (tracked, not linted).

## 3. Directory tree (every dir self-documents via its README)
```
src/
  engine/        engine.py base.py context.py logger.py        (always in dist)
  phases/<kind>/<impl>/  the LIBRARY (folder per impl + nested .Params)
  strategies/<name>.py   named STRATEGY_CONFIGs (direct class refs)
  main.py        selects ACTIVE strategy + bootstraps engine
  universe.py    cloud static universe import
tests/           MIRRORS src/ 1:1  + harness/ + integration/ + conftest.py
build/cloud_package.py   AST closure → flatten src/→dist/ + manifest + metadata
dist/            GENERATED, tracked, NOT linted — flat artifact LEAN runs (local+cloud)
sweeps/          driver.py + grids/ + runs/[ignored] + reports/   (config-permutation research)
results/         bt-results.csv + schema.md   (master ledger, provenance-pinned)
backtests/[ignored]  data/[ignored]  lean.json(→dist/)
scripts/ research/ docs/ ui/ archive/ zz_handoffs/   CLAUDE.md README.md CONVENTIONS.md
```

## 4. The engine
- `PHASE_ORDER` is a list incl. `FIRE_*` sentinels (fire_entries after cash, fire_exits after exit_*, fire_adds after adds, fire_trims after profit).
- A `regime`/`cash` block scopes to the ENTRY pipeline ONLY — exit/stop/trail phases run regardless (oracle behaviour; PHASES.md §3). `diagnostics` + `circuit_breaker` always run.
- `PhaseContext` = LEAN read-only refs + a fresh `BarState` per bar. Phases write intents via `apply(kind, result)`, keyed by `(kind, module)`, rejecting true double-writes. The engine fires from the typed BarState lists at sentinel boundaries.
- Engine refuses to start on charter violation (count caps / time exits / `adds` without `gross_exposure_cap`) — fail loud, no silent fallback. Logs every phase `version_marker` at init.

## 5. Build → deploy → run
```
src/ (dev, typed) ──build/cloud_package.py──▶ dist/ (flat, enabled-phase closure)
                                              + _manifest.json (phases, markers, config-hash)
                                              + _metadata.py  (commit, config-hash, data-fingerprint)
dist/ ──▶ LEAN local backtest   (via lean-bt.sh, marker-verified)
dist/ ──▶ QC cloud deploy        (via QC API /files/update)     ⇒ SAME artifact ⇒ parity
```

## 6. Workflows
- **New phase:** `feat/phase-<kind>-<impl>` worktree → build+test → PR gate (unit tests + parity + header + charter + build-script tests) → rebase → ff-merge → library grows. Decoupled from champion status.
- **Switch strategy:** edit `ACTIVE_STRATEGY` in `main.py` → rebuild → redeploy.
- **Sweep:** `sweeps/driver.py` enumerates a grid over the library → isolated parallel LEAN runs (unique project/local-id/cache, data symlinked, marker-verified) → leaderboard → promote winners to `results/bt-results.csv`.

## 7. Guards (anti-regression)
- Build script is unit-tested (single point of failure for parity).
- `dist/_metadata.py` logged on startup; results named by (commit + config-hash + data-fingerprint).
- No phase reads files via relative paths — all assets injected via typed params (so the closure packager is complete).
- Validation gates G1–G5 (incl G5 DSR/PBO #202) + the acceptance contract (#203) on PR.

## 8. References
v1 history: `git show <pre-v2>:docs/ARCHITECTURE.md`. Design session 2026-05-30 (web + Perplexity + Gemini). Related: #183 harness fidelity, #194 CI, #202 G5, #203 acceptance contract, PHASES.md (per-phase contracts).
