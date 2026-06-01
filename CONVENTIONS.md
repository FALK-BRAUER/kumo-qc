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

Structural guards the engine DOES enforce at init (not param-name games): `_validate_known_kinds` (a configured phase kind absent from `PHASE_ORDER` → ConfigError, no silent no-op) and `REQUIRED_PHASES` (these MUST be present).

**Fail-loud phase stack (#270 — extends #261's fail-loud-on-degraded-data to the config).** `REQUIRED_PHASES = (universe, signal, sizing, entry, exit)` — entry + exit are now REQUIRED. There is **NO implicit execution default**: a config that would fire entries with no wired entry-confirm phase, or exits with no wired exit phase, raises `DegradedConfigError` at init and refuses to run. A blind-open / placeholder market-on-open entry is a **test/variant FIXTURE only**, never a silently-running champion. (Rationale: the daily-MOO `champion_asis` traded a phantom model through all of #262/#268 precisely because nothing forced "no entry-confirm wired" to crash. This gate is that crash.)

**Champion vs fixture (#270).** `champion_asis` (signal→sizing→implicit-MOO, daily, no entry/exit-confirm) is a **blind-entry FIXTURE** for regression/parity scaffolding — it correctly fails the gate above and may NOT be deployed as a champion. A champion MUST wire the full daily-signal → intraday-confirmed-execution stack. The forward champion is `champion_intraday`.
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
- **#262/#268 MOO-parity is RETIRED (#270).** The local↔cloud "1-bar entry-fill offset" was a SYMPTOM of the wrong blind-market-on-open model (the engine blind-filled an open it should never have filled), not a parity defect to fix. It retires with that model. Parity is re-established on the NEW daily-signal→intraday-confirmed model — and the same delivery-timing question now applies to the **intraday (5-min) clock**: confirm local and cloud deliver intraday bars on the same clock (de-risk with a two-clock SMOKE BT before the full build, then re-baseline). Do not resurrect the MOO-parity chase.
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
- **`dist/` ALWAYS tracks the ACTIVE CHAMPION.** Variant/experiment MEASUREMENTS build into a THROWAWAY dir (`dist_tmp/`, gitignored), NEVER committed over `dist/`. A variant build must never displace the champion's deployable. `src/strategies/<variant>.py` configs stay (opt-in); only `dist/` tracks the champion. **(#270: the champion is the intraday-confirmed model `champion_intraday` once it lands; `champion_asis` is the retired blind-entry FIXTURE and is NOT a valid `dist/` target — it fails the fail-loud gate. Until `champion_intraday` exists, `dist/` may hold the asis fixture ONLY for the Phase-2 behaviour-unchanged parity step, clearly marked as the fixture.)**

## Data (local backtest substrate)
- `data/` = RAW daily OHLCV (built from Massive SIP parquet, `scripts/build_daily_from_parquet.py`) + RAW intraday (below). **Never back-adjusted, never mixed** (adjusted corrupts Ichimoku — the 7x-calibration lesson).
- Zips are gitignored; `data/MANIFEST.json` (the **data fingerprint**) + `data/README.md` are tracked.
- **Every result pins to the data fingerprint** (carried in `dist/_metadata.py`). Local and cloud must run the same data state — verify the fingerprint before trusting parity.

### Intraday data = 5-min Massive stored as LEAN "minute" zips (#275, Option C — read this)
- Our Massive intraday feed is **natively 5-minute** (78 RTH bars/day = George's BCT decision cadence). LEAN has no native 5-min resolution, so `scripts/build_minute_from_parquet.py` stores the 5-min bars in the **`minute/` tree** and the intraday execution clock consumes them **DIRECTLY — NO consolidator** (Option C, HQ-approved). True 1-min is NOT pursued (we don't have it, can't synthesize it, and 5-min IS the decision cadence — finer would be wrong).
- **HONESTY (loud, so no reader/indicator assumes true 1-min):** the `minute`-resolution zips carry **5-MIN bars**; the intraday execution timeframe **IS 5-min by data construction**; intraday indicator **periods are in 5-MIN-BAR units** (e.g. an intraday Tenkan(9) spans **45 min**, not 9).
- **FAIL-LOUD spacing guard (#261 class):** the builder asserts ~300s bar spacing and **RAISES `SpacingError`** on a true-1-min/irregular feed — a data mislabel can't silently corrupt the 5-min intraday indicators. (`tests/data/test_build_minute.py`.)
- **PARITY (CRITICAL, #277):** the cloud-confirm BT MUST run on this SAME 5-min-as-minute data (upload it to QC), **NOT** QC's native 1-min minute data — else local(5-min) ≠ cloud(1-min) is a NEW parity surface. The smoke proved delivery-timing is clean; this ensures the DATA is identical too. Carry to the #277 re-baseline.

## Execution environment (how LEAN actually runs — kills the Docker confusion)
- **Local LEAN runs via the `lean` CLI inside the `quantconnect/lean` DOCKER image (engine v2.5.0.0)**, with LOCAL data/map-file/factor/object-store providers (`lean.json`: `LocalDiskMapFileProvider`, `LocalDiskFactorFileProvider`, `DefaultDataProvider`, `LocalObjectStore`). **Local PROVIDERS, Docker ENGINE** — the 2026-05-26 "local setup" made the DATA local, NOT the engine. `DOCKER_HOST` must point at the user's docker socket (`unix:///Users/falk/.docker/run/docker.sock`; the default `/var/run/...` links to the wrong user). "Local providers" ≠ "no Docker" — do not conflate.
- **Dual execution model (#270, Falk):**
  - **Docker lean-CLI = the FAITHFUL runtime.** It is QC's own image, closest to cloud → use it for point tests, validation, parity, and cloud-confirm. The recorded champion/baseline numbers run here.
  - **Direct LEAN (native engine, no Docker) = the SWEEP runtime.** Docker per-run overhead × many configs is too slow for mass backtests, so sweeps run the engine natively for speed. **NOT set up yet** (Docker-only on disk today) — standing up direct-LEAN + the reconciliation below is a SWEEP ENABLER (flag in #214 / a new enabler ticket), NOT on the engine-rebuild critical path. (Second reason for direct-on-sweep, Falk: the Docker bind-mount does NOT follow an inner `data/equity → …` symlink — only a whole-`data` symlink resolves — a per-run fragility direct LEAN avoids. For a LOCAL point-test/validation BT, Docker is correct + fine; the worktree `data/` must be a WHOLE-dir symlink for any Docker BT.)
  - **GATE — direct≈Docker reconciliation (a NEW parity surface).** Before trusting ANY sweep result, a one-time reconciliation must prove the direct-LEAN engine matches the Docker/cloud engine on a reference config (same discipline as local≈cloud — don't assume direct==Docker; engine builds/versions can differ). A sweep finding on an unreconciled direct engine is not trustworthy.
- **Version pin (#270 reference clone).** Local engine = LEAN **v2.5.0.0** (Python 3.11.9). The version-matched LEAN SOURCE reference clone (for reading bar-delivery / consolidator / fill-model internals during the rebuild) pins to v2.5.0.0. CLOUD's engine version is NOT assumed equal — confirm it from a cloud BT log header before relying on a version match.

## Git workflow
- **Rebase, never merge-commit.** Linear history. Rebase a feature branch onto latest `main`, then `--ff-only` merge.
- One feature branch = one worktree. **Delete the branch + worktree after integration.** Each experiment/phase in its OWN worktree off mainV2; `data/` symlinked to the main repo (worktrees without the symlink silently fail all data requests). (#267 Part B — worktree isolation.)
- **Explicit `git add <paths>` only — never `git add -A`/`.`** Stage the specific files you changed. A worktree carries gitignored build/data churn (`dist_tmp/`, backtests, the `data` symlink swap, throwaway lean projects); a blanket add stages junk or a champion-displacing `dist/`. The reviewer checks `git diff --stat` is exactly the intended scope. (#267 Part B.)
- **Push immediately** after every clean commit (the 2026-05-23 unpushed-loss lesson).
- Conventional Commits.

### Worktree isolation discipline (#273 — never share a working tree)
The shared-working-tree collision (HQ + workers + the daily-brief pipeline all flipping branches in ONE checkout → clobbered untracked edits, ran each other's code) is forbidden by construction:
- **One actor = one worktree.** Every worker, the orchestrator, HQ doc-edits, and the daily-brief pipeline each operate in their OWN git worktree. NEVER `git checkout <other-branch>` in a tree another actor is using. The main checkout (`/Users/falk/projects/kumo-qc`) is not a workspace to flip branches in.
- **HQ/doc edits commit immediately** — never leave untracked edits in a shared tree for another actor's checkout to clobber.
- **`lean backtest` compile-cache isolation:** concurrent runs sharing a project name share LEAN's compile cache → one run executes another's compiled code (the 2026-05-29 e40c-ran-e40b incident). Each worktree gets a unique `config.json` `local-id` (scripts/lean-bt.sh derives it from cwd); verify the VERSION_MARKER in the run's `code/main.py` confirms YOUR code ran.
- **Branch base check before PR:** a branch cut before another change landed on the base will REVERT that change in its PR diff (the #280 pre-A1 catch). Rebase onto current base before opening the PR; verify `git diff --stat base..HEAD` is exactly the intended scope, no spurious reversions.

### Destructive-op discipline (#273 — backup before any irreversible action)
Destructive git ops (stash drop/clear, `branch -D`, history rewrite, force-push, worktree remove) require, IN ORDER:
1. **Explicit authorization** — Falk/HQ sign-off for the SPECIFIC scope + count (a count discrepancy vs the authorization → STOP and re-confirm; the 27-vs-10 stash catch).
2. **A recoverable backup FIRST** — a full `git bundle --all` to `~/reference/kumo-qc-backups/` AND archive each to-be-dropped ref under `refs/archive/<name>-<date>` (stashes recover as branches even after `stash clear`). Verify the backup exists before the drop.
3. **Then execute + verify** the archive refs survive the drop (the recovery path stays intact).
Never bulk-drop on your own read of "stale"; never skip the backup because it's "obviously junk."

## Look-ahead safety (the #268 lesson — enforced on the intraday clock, #270)
- **Consume only COMPLETED bars.** Act in the consolidator's bar-close handler; never read a forming/partial intraday bar. An intraday-Tenkan/volume confirmation uses the last *completed* 5-min bar.
- **No cross-clock leakage.** The T+1 intraday execution path must NOT read T+1's *daily* bar — that daily bar embeds T+1's close (= look-ahead, the exact class that flagged the #268 grid). Daily decisions use bars through T's close only.
- **`history()` ends strictly before `self.time`** (forward-only guard; the #213f/#259 daily-seed drop-rows-≥-today, applied to the intraday path too).
- A **fail-loud negative test** asserts the engine does NOT act on a forming/future bar (raises or skips-loud) — never silently uses it.

## Testing
- `tests/` **mirrors `src/`** 1:1 (`tests/<path>/test_<mod>.py`). Shared primitives in `tests/harness/`, cross-cutting in `tests/integration/`.
- Parity tests run the built **`dist/`**, not `src/`.
- **Functional unit tests are mandatory — not structural.** Each phase + selection function has BEHAVIORAL tests: real(istic) bar inputs → assert the actual decision/output is correct, plus the edge + failure cases (empty input, boundary floor values, ties, missing dates, None substrate). Import-only / "params exist" / "it instantiates" tests do NOT count as coverage. A phase merges only when its functional behavior — including its failure modes — is tested. (e.g. selection floors: `apply_floors` passes/fails tickers at/above/below each floor correctly + boundary; `rank_and_cap`: ranks by DV DESC + cap takes the right top-k + shuffle→same order; ranking phase: `(score, DV)` order + shuffle→identical output, the #182 determinism test; signal: BCT score correct on known bars + golden-master vs the canonical scanner.)

## Anti-drift
- **Every non-hidden directory has a `README.md`** (3-5 lines: what it holds / what goes here / what doesn't). Create/update it when you touch a directory. This is how the structure stays honest.
