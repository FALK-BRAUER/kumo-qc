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

## Variant strategy (PR gate — the enforceable subset)
The boundary rules + rationale live in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §9. These four are the reviewer-enforced gate on every new variant:
- **NEW-IMPL by default.** A parameter is for **same-algorithm scalar tuning only**. Branching over *algorithms* (`if self.params.mode == "A": … else: …`, a bool that toggles which of two algorithms runs) ⇒ **split into sibling impls**, never a flag. (Review test: "describe the change without the words *if* or *instead*" → yes ⇒ PARAM, no ⇒ NEW IMPL.)
- **`space()`-required.** Every phase `.Params` declares a `space()` classmethod returning the typed sweepable axes (`{field: ParamAxis}`) — the single, drift-proof source of the search space, co-located with the code (never in the sweep driver). A field added without a matching `space()` entry is a one-file reviewable miss.
- **Catalog-tuple-required.** Each kind enumerates its impls via one typed tuple — `<KIND>_PHASES: tuple[type[<Kind>Phase], ...]` — the sweep driver's only enumeration source. No discovery by reflection, no string lookup.
- **No-string-registry-in-core.** Wiring is by direct class reference (`Slot(impl=SomePhase, ...)`). A string→class registry exists only at a future external-config edge, confined to a thin `resolve(name) -> type[Phase]` adapter that immediately yields a typed `Slot`. Strings never enter the engine or config core.

## Phases (library members)
- Live in `src/phases/<kind>/<impl>/<impl>.py` with a mirror test in `tests/phases/<kind>/<impl>/`.
- **No phase reads files via relative paths.** All external assets are injected through typed params. (Otherwise the closure packager misses them and cloud breaks.)
- Each phase declares `PHASE_KIND`, `REQUIRES_UPSTREAM`, `PROVIDES_DOWNSTREAM`, a `version_marker`, and a mandatory file header (tested params + setup + charter + changelog).
- **Merge a phase when it is correct** (tests + parity + charter + header pass) — independent of whether it improves the champion.

## Charter rules

**No count caps** and **no time-based exits** are RULES — enforced by these conventions + code-review, NOT by a hardcoded engine param-name blocklist. (The former `FORBIDDEN_PARAMS` engine scan was removed: a name-list is brittle — it misses novel names and gives false safety. A reviewer judges intent; a blocklist judges spelling.)
- **No count caps** (`max_positions`, `max_lots`, `max_adds`, `max_pyramid_lots`, `max_slots`, ...). Bound exposure with `gross_exposure_cap` (a % rule), never a count. *(review-enforced rule)* (This is about POSITION count — how many you HOLD. It is DISTINCT from the universe `coarse_max` scan-breadth cap — how many names you SCAN — which is a legitimate dynamic-universe param, not a position cap. Do not conflate the two.)
- **No time-based exits** (`max_hold_days`, `exit_after_days`, ...). Exits are signal/structure-based (rotation / trail / cloud-breach), never "held N days." *(review-enforced rule)*

**Explicit exposure only — the one STRUCTURAL invariant the engine still enforces** (`validate_invariants`, refuses to start otherwise): if `adds` is enabled, `gross_exposure_cap`/`portfolio_risk` MUST be enabled. This can't be gamed by renaming, so it stays in code.

Structural guards the engine DOES enforce at init (not param-name games): `_validate_known_kinds` (a configured phase kind absent from `PHASE_ORDER` → ConfigError, no silent no-op) and `REQUIRED_PHASES = (universe, signal, sizing)` (these MUST be present).
- **NO FROZEN / snapshot universe — anywhere.** No 326, no hardcoded same-every-day ticker list, in code, config, data, or tests. The FROZEN snapshot was the root of the slot-tiebreak / data-divergence / parity-chasing time-sinks and **proved nothing** — eradicated. Which tickers a strategy selects = the dynamic selection gate + universe phase, pinned by config-hash; the substrate (the zip set) is fingerprinted separately.
- **Selection pipeline = dynamic `floors → rank → cap`, point-in-time, recomputed daily. A rank and a cap are REQUIRED, not forbidden** — what's forbidden is *freezing* the list. Per Falk's Y model, the floors are applied at the **SELECTION GATE** (`src/runtime/lean_entry.py::_coarse_selection`, the once-daily `add_universe` callback that runs the SAME code path local + cloud): each trading day it maintains a rolling dollar-volume per coarse name, applies the tradeability floors (`min_price`, `min_avg_dollar_volume` — `runtime.universe_select.apply_floors`, before Ichimoku), then ranks DV-desc and caps `coarse_max` (`rank_and_cap`), and **subscribes ONLY the qualifying ranked set** (so only those names get tracked + Ichimoku'd — no 2x indicator load). There is **NO separate per-bar `filter` phase** — the floors bound SUBSCRIPTION at the gate, not in a phase. The **`universe` phase** (`dv_rank_cap`) then EXPOSES that live-selected ranked set to the pipeline. (`filter` remains a known kind in `PHASE_ORDER` for a future strategy that genuinely needs a per-bar substrate reduction, but it is NOT required and the champion does not use one.)
- **The rank MUST be deterministic and IDENTICAL local + cloud.** Selection rank = dollar-volume DESC with a ticker-asc tiebreak; entry-priority ranking = `(score DESC, dollar-volume DESC)`, **NEVER alphabetical / insertion-order**. The #182 scar was local-alphabetical vs cloud-volume → different buys → irreproducible BTs. Consistency both sides is the fix; removing the rank is NOT. (Selection DV-rank lives in the selection gate + the `universe` phase; entry-priority `(score, DV)` rank is the separate `ranking` phase.)
- **NO fixed slots, NO day-holds / max-holds / max-hold-days, nothing of that family.** These are count-caps + time-caps by another name — forbidden. Position count is governed by `gross_exposure_cap` + signal rarity; exits are rotation / trail / cloud-breach (principled), never "held N days."

## Retrofits — principled re-expression (do NOT port the mechanic)
The #218 retrofit experiments often USED forbidden mechanics (fixed slots, max-positions, max-hold-days, day-based exits). **We do NOT carry those over.** When retrofitting an old idea into the v2 library:
- Take the INTENT, drop the mechanic.
- Re-express via a **principled KPI-based or $-risk-based** approach: exposure via `gross_exposure_cap` (% rule), sizing via $-risk, exits via signal/structure (rotation/trail/cloud/kumo-flip), selection via dynamic universe + KPI ranking.
- A retrofit that can only be expressed as a fixed slot / max-hold is REJECTED, not ported. The library accepts only principled forms.

## Parity (cloud vs local)
- Goal = **short-timeframe REPRODUCIBILITY, to a reasonable extent**: local == cloud on a SHORT window (days), same code (`dist/`) + same substrate (fingerprint), within tolerance.
- **NOT** full-FY exact-match — the cloud-vs-local data-vendor residual is a known irreducible; chasing it is a rabbit-hole (cloud = ground-truth).
- **NOT** parity against a fixed-universe oracle (326 proved nothing).
- Refactor-correctness is a SEPARATE check: per-phase, universe-agnostic golden-master (v2 phase logic == monolith logic on a sample of tickers) — not an end-to-end fixed-universe parity.
- **Divergence-debug protocol** — when cloud ≠ local on the short-window check, do NOT chase the residual blindly. Run a SHORT window, pull BOTH cloud + local logs + trade lists, and DIFF them to the mechanical root-cause (this is how #182 — the alphabetical-vs-volume rank — was found). A divergence is NOT dismissable as tolerance noise until the diff proves it is the known cloud-vendor residual. This guard is how we avoid repeating the days-long debugging scars.
- **v2 is the corrected RAW pipeline — judged on its OWN merits, NOT a champion clone.** The v1 champion's numbers were computed with ADJUSTED prices (SPY + traded equities via `add_equity` default); v2 is RAW everywhere — SPY, universe, traded equities (the 1.079 / 2649e2e lesson: adjusted prices corrupt Ichimoku). So the v2 baseline will DIVERGE from the champion's adjusted numbers **by design**. Validate v2 on its own merits (G1–G5 / DSR / PBO), **NEVER by matching a champion figure** — matching an adjusted-data number means reintroducing the contamination v2 exists to remove (same artifact class as 1.079). Golden-master stays logic-correctness on IDENTICAL input bars (v2 phase logic == monolith logic given the same raw bars), never end-to-end number-matching against the champion.

## Build / deploy / dist
- LEAN runs the **`dist/`** artifact — both local and cloud. No `if cloud:` branch in strategy code.
- `dist/` is **generated + git-tracked + NOT linted** (mypy excludes it). Never hand-edit it.
- The build (`build/cloud_package.py`) packages ONLY the active config's phase closure, and is itself unit-tested.
- Every result is pinned to **(git commit + config-hash + data-fingerprint)** via `dist/_metadata.py`, logged on startup. No result without that pinning enters `results/bt-results.csv`.
- **`dist/` ALWAYS tracks the ACTIVE CHAMPION (`champion_asis`).** Variant/experiment MEASUREMENTS build into a THROWAWAY dir (`dist_tmp/`, gitignored), NEVER committed over `dist/`. A variant build must never displace the champion's deployable. `src/strategies/<variant>.py` configs stay (opt-in); only `dist/` tracks the champion.

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
- **Functional unit tests are mandatory — not structural.** Each phase + selection function has BEHAVIORAL tests: real(istic) bar inputs → assert the actual decision/output is correct, plus the edge + failure cases (empty input, boundary floor values, ties, missing dates, None substrate). Import-only / "params exist" / "it instantiates" tests do NOT count as coverage. A phase merges only when its functional behavior — including its failure modes — is tested. (e.g. selection floors: `apply_floors` passes/fails tickers at/above/below each floor correctly + boundary; `rank_and_cap`: ranks by DV DESC + cap takes the right top-k + shuffle→same order; ranking phase: `(score, DV)` order + shuffle→identical output, the #182 determinism test; signal: BCT score correct on known bars + golden-master vs the canonical scanner.)

## Anti-drift
- **Every non-hidden directory has a `README.md`** (3-5 lines: what it holds / what goes here / what doesn't). Create/update it when you touch a directory. This is how the structure stays honest.
