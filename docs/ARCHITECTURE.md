# kumo-qc Architecture v2 — Type-Safe Phase Library

**Status:** Canonical charter (2026-05-30, Falk; **revised 2026-06-01 for the two-clock intraday execution model, #270**). Supersedes v1 (`algorithm/performance_bct` layout).
**Epic:** #208; **execution model #270** (intraday execution, GH#25).
**Conventions:** [CONVENTIONS.md](../CONVENTIONS.md).
**Owner:** fintrack HQ (structure + verification) + kumo-qc orchestrator (code + BTs).

The repo root IS the strategy project. A strategy = a typed `STRATEGY_CONFIG` selecting composable **phase** plugins from a library, run by one engine in a fixed `PHASE_ORDER`. Built to a flat `dist/` that LEAN runs both locally and on cloud.

> **#270 model correction (read first).** The BCT strategy is **daily signal → intraday execution**: the daily/weekly Ichimoku signal decides *which* names after close T (the candidate list for T+1); on T+1 the engine does **NOT** blind-buy the open — it waits for **intraday confirmation** (intraday-Tenkan reclaim + rising volume, ~first 2h) before firing, and exits on **intraday stop-market** orders. The engine therefore runs on **two clocks** (a daily decision clock + an intraday execution clock). An entry that fires market-on-open with no confirmation phase is a **blind-entry FIXTURE** (the retired `champion_asis`, the −0.616 artifact), **never a champion** — the engine fails loud (`DegradedConfigError`) on a config that would fire without a wired entry + exit phase. The earlier daily-only, market-on-open engine + the #262/#268 MOO-parity effort are **retired** (they optimised a model the strategy was never meant to use). See §4 (the engine) and §10 (the execution model).

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
9. **Two-clock execution (#270)** — the engine runs phases on TWO clocks: a **daily decision clock** (universe/signal/regime/ranking — picks WHICH names, after close T → candidates for T+1) and an **intraday execution clock** (entry_selection/entry_timing/sizing/fire/stops/trail/exits — decides WHEN to fire on T+1's intraday bars). Each phase declares its clock (`PHASE_RESOLUTION`); the daily/intraday subsets are precomputed at config-build, not filtered per tick. Daily-only is the legacy special case, not the model.
10. **Fail-loud phase stack (#270, extends #261 to the config)** — `entry` and `exit` are REQUIRED phases. There is **no implicit execution default**: a config that would fire entries with no wired entry-confirm phase, or exits with no wired exit phase, raises `DegradedConfigError` at init and refuses to run. A blind-open / placeholder entry is a **test/variant fixture only**, never a silently-running champion. (Had this gate existed, the daily-MOO `champion_asis` would have crashed as "no entry-confirm wired" instead of silently trading a phantom model for #262/#268.)
11. **Look-ahead safety on the intraday clock** — phases consume only COMPLETED consolidated bars (act in the consolidator's bar-close handler, never a forming bar); the T+1 intraday path must NOT read T+1's daily bar (which embeds T+1's close = look-ahead); `history()` ends strictly before `self.time`. Enforced by a fail-loud negative test.

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

## 4. The engine (two-clock, #270)
- `PHASE_ORDER` is a single list incl. `FIRE_*` sentinels (fire_entries after cash, fire_exits after exit_*, fire_adds after adds, fire_trims after profit). It is the single source of phase SEQUENCING for both clocks.
- **Two clocks, two entry points.** Each phase declares `PHASE_RESOLUTION ∈ {daily, intraday}`. At config-build the engine PRECOMPUTES the daily subset and the intraday subset of `PHASE_ORDER` (not a per-tick filter — avoids re-deriving the split every tick, the brittleness that produced the double-rebalance + #268 day-boundary bugs). Then:
  - `on_daily_bar(ctx)` — runs the daily-clock phases (universe/signal/regime/ranking) after close T → produces the candidate list + a SNAPSHOT of the signal context (signal price, daily Kijun) per candidate, stored for T+1. Does NOT fire entries. Driven by a scheduled after-close event.
  - `on_intraday_bar(ctx)` — runs the intraday-clock phases (entry_selection incl. the pre-flight staleness gate, entry_timing, sizing, FIRE_ENTRIES, stops/trail, exit_*, FIRE_EXITS) against the standing candidate list + the current COMPLETED intraday (5-min) bar on T+1. Fires orders.
- **Pre-flight staleness gate (first intraday phase, #270).** Before any intraday confirmation, a candidate is re-validated against its daily snapshot: if T+1 has gapped away from / below the signal thesis (price, Kijun), the candidate is INVALIDATED — don't enter a broken thesis. This is George's gap-up discipline expressed as a phase.
- **The fire seam (Command pattern).** Phases emit a typed `OrderIntent{order_type ∈ market_on_open|stop_market|limit|market, price, stop, qty, ...}`; ONLY the `FIRE_*` sentinels call the QC order API, dispatching on `intent.order_type`. The entry_timing phase SETS the order type/price (e.g. confirmed → market; §4 Gate-5 day-type → stop/limit); exits emit stop-market for intrabar fills. The hardwired `market_on_open_order` is retired — it becomes one order_type among several.
- A `regime`/`cash` block scopes to the ENTRY pipeline ONLY — exit/stop/trail phases run regardless (oracle behaviour; PHASES.md §3). `diagnostics` + `circuit_breaker` always run.
- `PhaseContext` = LEAN read-only refs + a fresh `BarState` per tick (daily or intraday). Phases write intents via `apply(kind, result)`, keyed by `(kind, module)`, rejecting true double-writes. The engine fires from the typed BarState lists at sentinel boundaries.
- **Engine refuses to start on charter violation, fail loud, no silent fallback:** count caps / time exits / `adds` without `gross_exposure_cap` (charter), AND (#270) `entry`/`exit` not wired or an implicit-execution-default config → `DegradedConfigError`. Logs every phase `version_marker` + its `PHASE_RESOLUTION` at init.

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
v1 history: `git show <pre-v2>:docs/ARCHITECTURE.md`. Design session 2026-05-30 (web + Perplexity + Gemini). Intraday-model design 2026-06-01 (orchestrator + Perplexity + Gemini, all converged; #270). Related: #183 harness fidelity, #194 CI, #202 G5, #203 acceptance contract, PHASES.md (per-phase contracts), [GH#25 intraday spec](notes/GH25_intraday_design_spec.md), #270 (execution-model epic), #261 (fail-loud data → extended to the phase stack), [research/parity/269-intraday-build-approach.md](../research/parity/269-intraday-build-approach.md).

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

## 10. The execution model — daily signal → intraday confirmed execution (#270)

This is the load-bearing correction of 2026-06-01. The strategy was always designed as **"Daily Signal, Intraday Execution"** ([docs/notes/GH25_intraday_design_spec.md](notes/GH25_intraday_design_spec.md)); the engine was built daily-only and the champion blind-filled the open, so the design was never realised. BCT-9 validated **real intraday-confirmed alpha** on George's recorded entries (≈85% filled in the first 2h, volume-confirmed) — a blind-MOO model cannot capture it. The intraday model is the corrected foundation, not an enhancement.

### The two steps
1. **Scan after close T → candidate list for T+1** (daily clock). The daily/weekly Ichimoku 8-condition signal picks WHICH names. This is unchanged from today and correct. Each surviving candidate carries a **snapshot** of its signal context (signal price, daily Kijun) for the staleness gate.
2. **On T+1, confirm intraday, then fire** (intraday clock). Do NOT blind-buy the open. The execution phases run on 5-min bars:
   - **pre-flight staleness gate** — invalidate if T+1 gapped away from the thesis;
   - **entry confirmation** — intraday-Tenkan reclaim + rising volume (GH#25 §3.2), within the first ~2h;
   - **fire** — the confirmed order via the `OrderIntent` seam (market once confirmed, or a §4 Gate-5 day-type stop/limit);
   - **exits** — intraday **stop-market** (GH#25 §3.3), so stops fire intrabar on the break, not next-open.

### Confirmation mechanic — LOCKED
The confirmation is the **GH#25 intraday-Tenkan reclaim + volume** trigger, evaluated on completed 5-min bars. The #253 **daily** §4 Gate-2 (C1–C4) gate is **RETIRED as the proven-wrong proxy** — it degraded Sharpe to −1.016 precisely because a once-daily snapshot is not an intraday touch (its own measurement doc flagged this).

### Champion vs fixture
`champion_asis` (signal→sizing→implicit-MOO, daily, no entry phase) is **reclassified a blind-entry FIXTURE** used only for regression/parity scaffolding. It is NOT a champion and cannot run as one — it fails the fail-loud REQUIRED_PHASES gate (no entry/exit wired). The forward champion is `champion_intraday` (the confirmed-entry model), measured against the asis fixture; the #262 baseline RESETS to the confirmed-entry numbers (neither −0.139 local nor −0.683 cloud — both were the phantom MOO model).

### Multi-timeframe data + indicators
- **Subscriptions:** dynamic 5-min subscriptions for the daily-selected candidates + current holdings ONLY (capped, parameterized, logged) — never the whole universe (the #213e OOM scar).
- **Indicators:** a parallel intraday indicator suite (intraday Tenkan/volume) fed by a 5-min `TradeBarConsolidator` + `register_indicator` + minute-history warmup, coexisting with the daily/weekly suite, scoped to the candidate set, feeds never mixed.
- **Data exists:** 5-min Massive Parquet (2021→2026, covers FY2025) is on disk — this is a data-WIRING task, not data-sourcing.

### Parity, recast (#262/#268 retired)
The MOO local↔cloud "1-bar offset" was a symptom of the wrong (blind-open) model and is retired with it. Parity is re-established on the NEW model: confirm that local and cloud deliver intraday (5-min) bars on the same clock (the #268 question recurs on the intraday clock — de-risk it with a two-clock SMOKE BT before the full build), then re-baseline. Cloud remains ground-truth; the goal stays short-window reproducibility within the known vendor residual, never full-FY exact-match.

### Build sequencing (see #270)
Phase 0 (these docs) → 1 (fail-loud gate + worktree isolation + two-clock smoke BT) → 2 (tick-routing split, behaviour-identical to the asis fixture) → 3 (intraday data pipeline) → 4 (the model: fire seam + intraday-Tenkan confirm + staleness gate + stop-market exits) → 5 (`champion_intraday` + re-baseline) → 6 (experiments on the correct baseline). **No code until Falk approves Phase 0.**
