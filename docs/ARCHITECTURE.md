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
cli/             Typer operator CLI (data|build|bt|deploy|sweep|lib) — dev tooling, NOT in dist/
research/        catalog/ experiments/ trade-analysis/ parity/ methodology/ ideas/ sources/  (analysis layer; no code)
backtests/[ignored]  data/[ignored]  lean.json(→dist/)
scripts/ docs/ ui/ archive/ zz_handoffs/   CLAUDE.md README.md CONVENTIONS.md
# scripts/ consolidates INTO cli/ (ARCH2-CLI); research/ flat files → categorized (ARCH2-R).
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

## 9. Variant Strategy (entry/exit/sizing/regime proliferation)
We experiment with many entry/exit/sizing/regime algorithms; this section is the rule for **when to extend a phase, when to build a new variant, and when to control behaviour via parameters vs new code** — so variation stays cheap, type-safe, and reproducible without the library rotting into flag-soup or copy-paste sprawl. Each phase **kind** owns a library of interchangeable implementations, each with its own nested typed `.Params`; a strategy composes them by direct class reference (`Slot(impl=SomePhase, params=SomePhase.Params(...))`). The variant catalog lives in [research/catalog/variant-catalog.md](../research/catalog/variant-catalog.md); the prior-art survey backing these rules is in [research/methodology/variant-architecture-references.md](../research/methodology/variant-architecture-references.md). (Drivers: Falk; synthesis of in-house + Perplexity + Gemini analysis, all three converged.)

### D1 — The boundary: PARAM vs NEW IMPL vs EXTEND
**Default verdict is NEW IMPL.** Reach for a parameter only for same-algorithm tuning; reach for extension almost never.

| You observe | Verdict | Why |
|---|---|---|
| A number/threshold/window/multiplier changes; code path identical | **PARAM** (field on the impl's `.Params`) | same algorithm, different magnitude; sweepable on a continuous axis |
| `if self.params.mode == "A": … else: …` branching over **algorithms** | **NEW IMPL** | each branch *is* an algorithm wearing a param's clothes — split it |
| A param is meaningful to A but **nonsense for B** (disjoint param sets) | **NEW IMPL** | disjoint `.Params` ⇒ disjoint classes |
| Different **inputs** or different **output shape** | **NEW IMPL** | not the same computation |
| You want to **sweep {A, B, C} categorically** | **NEW IMPL** | impls *are* the categorical axis of the sweep |
| Optional **guard/clamp**, default-OFF, same math, leaves past results byte-identical | **EXTEND** | strictly additive sub-mode of one algorithm |
| A boolean that toggles which of two algorithms runs | **NEW IMPL**, never a flag | bool-flag-soup → impossible states |

**The one-line tests (use in code review):**
- "Can I describe the change **without** the words *if* or *instead*?" → yes ⇒ PARAM; no ⇒ NEW IMPL.
- \> 2–3 `Literal`/enum modes with different code paths, **or** branch-on-type in > 2–3 places, **or** a phase class bloating past ~150–200 LOC purely from variant logic ⇒ split into impls.

**Failure modes this prevents:** treating new logic as a param → god-phase / boolean-flag soup (3 bools = 8 states, most invalid); treating a param as a variant → copy-paste sprawl (`AtrStop_2x`, `AtrStop_2_5x` as classes — a continuous knob you can no longer sweep continuously); over-extending → fragile base class (a small base change breaks N descendants).

### D2 — Co-locate the sweep space with the code (`space()` on `.Params`)
The searchable space **lives on the `.Params` dataclass**, never in the sweep driver (which is how it drifts — the LEAN `config.json`-separate-from-code failure mode).

```python
@dataclass(frozen=True)
class Params:
    atr_period: int = 22
    atr_mult: float = 3.0

    @classmethod
    def space(cls) -> dict[str, ParamAxis]:
        # the ONLY source of truth for this phase's sweepable axes
        return {
            "atr_period": IntAxis(low=14, high=40, step=2),
            "atr_mult":   FloatAxis(low=1.5, high=5.0, step=0.25),
        }
```

- **Drift-proof under mypy:** `space()` keys are field names — a typo or a field that doesn't exist fails at check/attribute time. Adding a field without adding it to `space()` is a one-file reviewable change.
- **Axis type, not raw tuples:** a small `ParamAxis` abstraction (`IntAxis`/`FloatAxis`/`CategoricalAxis`), **structurally compatible with optuna distributions** so the runner can later swap grid-search → Bayesian (TPE/CMA-ES) **without touching any phase**.
- **Named presets** for human-meaningful points (`AGGRESSIVE = Params(atr_mult=4.0)`), separate from the sweep grid.

### D3 — Enumerate variants with explicit typed catalogs, NOT a string registry
Per kind, one typed tuple is the sweep driver's enumeration source: `EXIT_PHASES: tuple[type[ExitPhase], ...] = (KijunTrailExit, WeeklyCloudBreachExit, ...)`.

- Keeps the direct-reference wins: mypy verifies each member satisfies the kind's Protocol; rename breaks loudly at check time; dead variants are detectable; a serialized run references a concrete versioned class (reproducible).
- Recovers the only thing a registry gave us — enumeration — with zero of its costs. A string registry is added **only** at a future external-config edge (a non-Python tool writing a sweep grid as YAML), confined to a thin `resolve(name) -> type[Phase]` adapter that immediately yields a typed `Slot`; strings never enter core (Nautilus's split: typed configs in-process, importable config only at the serialization boundary).
- A **`StrategySpace`** object models a sweep as the cartesian set of `Slot` choices × each impl's `space()` → a list of fully-typed, reproducible `StrategyConfig`s.

### D4 — Composition over inheritance for shared mechanics
Shared machinery (EOD stop evaluation, ATR computation, weekly-bar seeding) lives in **free helper functions** or thin mixins consumed by impls — **not** a fat `BaseStop` template-method base. The phase contract is a `Protocol`; impls share *code*, never *inheritance state* (backtrader's 1,700-line `Strategy` god-base is the cautionary tale).

### D5 — The mass runner must defend against overfitting BY DESIGN
The architecture makes param/structure explosion easy; the dominant real-world risk is therefore **curve-fitting noise**, not engineering elegance. The runner (#214) bakes in:
1. **No single-number results** — every config's output is the distribution across the mandatory 6 windows, never one backtest.
2. **Rank by stability, not peak** — primary score ≈ `mean(Sharpe) / std(Sharpe)` across windows, not best-window Sharpe.
3. **Complexity penalty (Occam)** — each phase declares a `complexity`; the leaderboard shows a complexity-adjusted score so the optimizer prefers the simpler config at equal performance.
4. **Robustness surface** — for top-N candidates, auto-run a local grid around the optimum; prefer flat regions, reject knife-edges.
5. **DoF budget per strategy** — a soft cap on total swept parameters, logged loudly when exceeded.
6. Inherits the charter invariants: no count caps, no time-based exits, no fixed slots, out-of-window validation.

### Decision summary (the rules, one screen)
1. **NEW IMPL by default.** Param only for same-algorithm scalars. `if mode==` over algorithms ⇒ split. Extend only for default-off orthogonal guards.
2. **`space()` on every `.Params`** — single, drift-proof, optuna-compatible source of the sweepable axes. Named presets for human points.
3. **Typed `*_PHASES` catalog tuple per kind** for enumeration. No string registry in core; only at a future external edge.
4. **Composition over inheritance** — Protocols + free helpers, no fat bases.
5. **Runner defends against overfitting** — 6-window distributions, rank by stability not peak, complexity penalty, robustness surface, DoF budget; charter invariants hold.

The enforceable subset of D1–D3 is a PR gate in [CONVENTIONS.md](../CONVENTIONS.md).
