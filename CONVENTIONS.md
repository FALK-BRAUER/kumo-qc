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
- **No count caps** (`max_positions`, `max_lots`, `max_adds`, `max_pyramid_lots`, `max_slots`, ...). Bound *exposure* with `gross_exposure_cap` (a % rule), never a count. (This is about POSITION count — how many you HOLD. It is DISTINCT from the universe `coarse_max` scan-breadth cap — how many names you SCAN — which is a legitimate dynamic-universe param, not a position cap. Do not conflate the two.)
- **No time-based exits** (`max_hold_days`, `exit_after_days`, ...).
- **Explicit exposure only** — if `adds` is enabled, `gross_exposure_cap` MUST be enabled.
- **NO FROZEN / snapshot universe — anywhere.** No 326, no hardcoded same-every-day ticker list, in code, config, data, or tests. The FROZEN snapshot was the root of the slot-tiebreak / data-divergence / parity-chasing time-sinks and **proved nothing** — eradicated. The substrate (the zip set) is fingerprinted separately from selection.
- **Candidate-set pipeline = dynamic `filter → rank → cap`, point-in-time, decomposed into phases. A rank and a cap are REQUIRED, not forbidden** — what's forbidden is *freezing* the list. Each trading day: the **`filter` phase** reduces the substrate by tradeability floors (`min_price`, `min_avg_dollar_volume`, `adv_window` — its own params, before Ichimoku) → the **`universe` phase** ranks the eligible set (baseline: dollar-volume DESC) and caps `coarse_max` (param; default unbounded). Recomputed daily, pinned by config-hash. (Known-good build: commits `52993ae` + `2649e2e`.)
- **The rank MUST be deterministic and IDENTICAL local + cloud.** Entry-priority ranking = `(score DESC, dollar-volume DESC)`, **NEVER alphabetical / insertion-order**. The #182 scar was local-alphabetical vs cloud-volume → different buys → irreproducible BTs. Consistency both sides is the fix; removing the rank is NOT. (Universe volume-rank lives in the `universe` phase; entry-priority `(score, DV)` rank is the separate `ranking` phase.)
- **NO fixed slots, NO day-holds / max-holds / max-hold-days, nothing of that family.** These are count-caps + time-caps by another name — forbidden. Position count is governed by `gross_exposure_cap` + signal rarity; exits are rotation / trail / cloud-breach (principled), never "held N days."
- **Fail loud on an unknown phase kind.** The engine validates every configured phase kind against `PHASE_ORDER` at init and raises `ConfigError` if a configured kind is absent. A configured phase that is never scheduled is a SILENT no-op (e.g. a `filter` phase that never runs → empty eligible set → no candidates, looking like "0 trades" not "misconfigured") — exactly the silent contamination this charter exists to prevent. No silent skips. (`filter` MUST be in `PHASE_ORDER`, before `universe`.)

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
- **Functional unit tests are mandatory — not structural.** Each phase has BEHAVIORAL tests: real(istic) bar inputs → assert the actual decision/output is correct, plus the edge + failure cases (empty input, boundary floor values, ties, missing dates, None substrate). Import-only / "params exist" / "it instantiates" tests do NOT count as coverage. A phase merges only when its functional behavior — including its failure modes — is tested. (e.g. filter: tickers at/above/below each floor pass/fail correctly + boundary; universe: ranks by DV DESC + cap takes the right top-k + shuffle→same order; ranking: `(score,DV)` order + shuffle→identical output, the #182 determinism test; signal: BCT score correct on known bars + golden-master vs the canonical scanner.)

## Anti-drift
- **Every non-hidden directory has a `README.md`** (3-5 lines: what it holds / what goes here / what doesn't). Create/update it when you touch a directory. This is how the structure stays honest.
