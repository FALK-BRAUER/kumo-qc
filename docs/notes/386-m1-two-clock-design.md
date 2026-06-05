# #386 M1 — Two-Clock Engine: relocate design (for HQ review BEFORE code)

Baseline: mainV2 f82809f (clean), worktree kumo-qc-386. Engine framework (engine.py PHASE_ORDER /
FIRE_ sentinels / slots) **STAYS** — strategy logic in modules only (the #378/#379 mistake).

## Current flow (what exists)
- Scheduled **after-close event** (`lean_entry.py:482`, `after_market_close(SPY, AFTER_CLOSE_MIN=10)`) →
  `_scheduled_decision` → `engine.on_data_with_ctx(ctx)` runs the FULL day chain **including the entry
  decision** → candidates armed for T+1.
- **5-min `on_data`** (`:980`) updates `_intraday[sym]` + runs `engine.on_intraday_bar(ictx)` (`:1016`)
  = entry_selection (gap_vol_confirm, open-30m `window_bars`) → entry_timing → FIRE_ENTRIES.
- BUG (the #382 2nd slot): names that don't confirm in open-30m fall to the **MOO-default/EOD** fill.

## Target flow (two clocks, entry decision on the 5-min tick)
**DAILY tick** (after-close event — KEPT, but trimmed to SELECTION/ARM only, NO firing):
- Day chain: `universe → signal(scanner) → regime → ranking → entry_selection → sizing → stops_initial`.
- Output = **armed candidate set**, each carrying `{thesis, entry_zone, invalidation_rule}`.
- Maintained ACROSS days: add new, **drop on thesis-break**, keep the rest armed (persistent watchlist,
  not a fresh daily scan). New engine state: `qc._armed` (dict sym→{thesis, zone, invalidation, armed_date}).
- **NO FIRE_ENTRIES on the daily tick.** The day chain ends at `stops_initial`.

**5-MIN tick** (`on_data` per bar — the relocated entry decision):
- For each armed candidate **near its entry_zone** (PROXIMITY-GATE — watch ON only when close to zone):
  `entry_trigger(this bar + preceding, time-of-day) → intraday_sizing → FIRE_ENTRIES`.
- `entry_trigger` = per-bar if-then → fire / wait / hold. Fire at the bar the condition is TRUE.
- **LOOK-AHEAD-SAFE:** evaluate using that bar + preceding ONLY (no bar-close/future peek) — causal.
- Unfired candidates STAY armed next bar until fire OR thesis-break. **No window, no MOO default.**

## Engine change (minimal, framework-preserving)
- `FIRE_ENTRIES` clock → **INTRADAY only** (today it resolves via entry_timing's clock; the day chain
  no longer reaches FIRE_ENTRIES). The day chain's terminal sentinel = after `stops_initial` (arm, not fire).
- The entry-chain co-clock guard stays — now it enforces the INTRADAY entry chain (entry_trigger →
  intraday_sizing → FIRE_ENTRIES all intraday). No new strategy logic in engine.py — only the
  clock-routing + the armed-set plumbing (a generic candidate-carry, module-agnostic).
- New phase KINDS: `entry_trigger` (intraday), `intraday_sizing` (intraday). `signal` becomes the real
  scanner (M2). `ranking`, `stops_initial`, `trail`, `exit` are day slots (some exist: ranking≈score-rank,
  stops_initial≈protective_stop, trail≈exit_hard).

## DELETE (legacy)
1. The after-close **entry decision/fire** — day chain stops at arming (no day FIRE_ENTRIES).
2. The **open-30m window** — `gap_vol_confirm` `window_bars`/`window_closed` → becomes an un-windowed
   per-bar `entry_trigger` module.
3. The **MOO-default / EOD-funnel** (2nd entry slot) — resolves #382 by construction.
4. The **stub signal** (`sample_bct.py` #228) — replaced by the ported real BCT scanner (M2).

## KEEP
PHASE_ORDER + FIRE_ sentinels + folder-per-phase + per-phase tests + the 5-min feed
(`Resolution.MINUTE`, `on_data`, `_intraday[sym]`).

## Milestone sequence
- **M1 (this):** two-clock relocate + legacy delete + the armed-set carry. Parity NOT expected (the
  behavior CHANGES by design — old S1 had the 2-slot bug). Validate by: day-chain arms candidates, 5-min
  entry_trigger fires them, ZERO EOD/MOO fills (the #382 path gone), behavioral tests on dummy bars.
- M2 real scanner · M3 entry_trigger module · M4 the ~10 catalog modules · M5 the 3 configs + diff=0 gate.

## OPEN QUESTIONS for HQ (before I cut code)
1. `entry_zone` + `invalidation_rule` source — from the scanner module (M2) per candidate, or a separate
   day-phase module? (Spec says the day chain produces `{thesis, entry_zone, invalidation}` — which slot
   owns it? I propose: signal(scanner) emits thesis+zone; entry_selection/a new `invalidation` slot owns
   the thesis-break rule.)
2. The armed-set carry: engine-generic state (`qc._armed`, module-agnostic) vs a phase that owns it?
   I propose engine-generic carry (it's framework plumbing, not strategy) — confirm that's not
   "strategy-in-engine".
3. Build M1 against a throwaway entry_trigger stub (so M1 = pure engine plumbing, testable) then M2/M3
   fill the real modules? (keeps M1 reviewable in isolation.)
