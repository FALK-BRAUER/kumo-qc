# #379 — Trim-side stop-resize floor-lifecycle + prover-gated profit-take (DESIGN/SCOPE)

*2026-06-05. Authorized build (HQ greenlight). Scope-then-build: this doc + test plan + code-review BEFORE any commit. Floor code — the #378 discipline applies (build fresh, careful, mutation-proven).*

## Why
The champion is **cash-locked** (#340-C / combined-cloud: +23–27% but ~18 names hold all the cash → new entries blocked for lack of capital). Headroom is the binding constraint. The non-leverage way to create headroom = free cash from the **never-proved slot-occupiers** (names that took a slot but never became monsters) via a **partial trim** — banking their small gain + recycling the capital, WITHOUT touching the proved monsters.

This is the LAST autonomous mechanic lever. Strong prior of failure (every winner-perturbing lever died this session: pyramid/rotation/hard-stop/exit/sidestep). The differentiator vs the dead rotation: **the prover-gate is a higher bar** — rotation evicted *gain-positive* names (which include developing winners → clipped them); profit-take trims only *never-proved* names (never +5% MFE → demonstrably not monsters). Plus it's a *partial* trim (keep a residual), not a full evict.

## Part A — the floor-lifecycle (the #378 sell-side analog, the hard prerequisite)
A partial trim on a stop-protected position leaves the resting GTC stop sized to the FULL qty → if it fires it OVER-SELLS the now-smaller position → long→short flip (the #276a GUARD-1 catastrophic class). So:
1. **On a trim, resize the protective stop DOWN to the remaining held qty** — mirror of #378's resize-UP-on-add. **VERIFIED (2026-06-05): NOT covered by the existing reconcile.** `on_order_event`'s reconcile fires on `{Canceled, Invalid}` ONLY (the #339-RUN1 fix) — a trim FILL (Filled/PartiallyFilled) does NOT trigger it. So #379 needs an explicit `_resize_protective_stop_for_trim` at FIRE_TRIMS — the exact mirror of `_resize_protective_stop_for_add` (engine.py): resize the stop to `-(held − trim_qty)` (i.e. `stop_qty + trim_qty`, LESS negative) FIRST (resize-DOWN is the safe direction — the stop is never over-sized → no over-sell), verify `is_success`, THEN submit the trim; resize-fail → skip the trim. ~30 lines, mirrors #378 1:1.
2. **Relax the FIRE_TRIMS guard** (`engine.py:512` `_guard_position_change_vs_protective_stop(..., "trim")`) to ALLOW the trim WHEN the resize-on-fill is wired (mirror how #378 relaxed the add-guard); keep fail-loud when unwired.
3. **Failure-gap + over-sell** handling: the engine FIRE_EXITS over-sell dedup (#339-RUN1) already guards double-exit; the trim must never leave the stop OVER-sized (the catastrophic direction). Reuse the verified primitive `qc.update_order_quantity`.

## Part B — the prover-gated profit-take phase (PgProfitTake)
- **Kind**: `exit_trim` (emits `trim_intents` = partial sells). Daily.
- **PROVER-GATE (asymmetric — the critical design, bake in from the start)**: trim ONLY a **never-proved** position (never reached +`prove_pct` (5%) MFE — a slot-occupier/fader). **EXEMPT every proved position** (≥+5% MFE = a potential monster → let it run full). Same gate that made the exit-model work (monster-sells = 0 every variant). A naive symmetric profit-take trims monsters → CAPS the run (HOOD +175%: trim-at-+50% banks 50, misses 125 = catastrophic) → dies like rotation/pyramid. The asymmetric one is the only version with a chance.
- **Trim trigger** (the never-proved fader, candidate mechanics to screen): (T1) held N days never-proved → trim X%; (T2) never-proved AND below daily Tenkan (stalled) → trim X%; (T3) never-proved AND a fresh higher-conviction candidate needs the cash. Start with T1 (pure age-gated fader cull) — simplest, no candidate coupling.
- **Trim size**: partial (e.g. 50% of the never-proved position), not full (keep a residual in case it blooms late — though the data says monsters prove early, so a long-never-proved bloom is rare). Frees cash for a new entry.
- **State**: per-position `{entry_date, proved}` (MFE-tracked, prove on `max(close,high) ≥ entry×1.05`, GC'd on close) — identical to the exit-model's prover state (reuse).

## Test plan (per-phase behavioral, Falk's rule — BEFORE the run)
- **Prover-gate teeth (mutation-proven)**: trim FIRES on a never-proved fader; trim DECLINES on a proved monster (even one in profit). Mutation: disable the gate → the decline test fails.
- **Trim trigger**: fires at the trigger condition; declines below it.
- **Floor-lifecycle** (engine, the over-sell-critical part): a partial-trim fill → the protective stop resizes DOWN to `-remaining_qty`; the over-sell guard still fires if the resize is unwired; the FIRE_TRIMS guard raises when the lifecycle is absent. Real-engine integration test (the test_fire_seam harness), mutation-proven.
- **Code-review (mandatory)** before commit — floor code.

## Risks / honest read
- The winner-perturbing prior: this MAY die like rotation. The bet is the prover-gate (+5% MFE bar) + partial-trim + targeting the real cash-lock constraint. The decisive test (window-then-FY, floor-proxy same-method vs S1): does prover-gated profit-take free cash that redeploys profitably WITHOUT capping monsters (monster-sells = 0) → net floor-proxy ≥ S1?
- If it dies too → the cash-lock is un-fixable without leverage (headroom = a Falk leverage decision) → ALL autonomous mechanic levers exhausted, S1 at the efficient frontier, the convergence is complete.

## Sequence
1. Part A floor-lifecycle (verify reconcile covers resize-down; relax the trim-guard; tests). 2. Part B PgProfitTake (T1) + tests. 3. code-review. 4. screen T1/T2/(T3) × Q1+Q3 floor-proxy vs S1, window-then-FY. Mirror the exit-model build exactly (it was clean).
