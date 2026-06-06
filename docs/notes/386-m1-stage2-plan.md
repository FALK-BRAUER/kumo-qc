# #386 M1 Stage-2 plan — relocate the entry decision to the two-clock _armed path

**For HQ review BEFORE any cut.** Stage-1 (arm-in-parallel + live `_assert_arm_parity`) is committed +
proven: `qc._armed` reproduces the legacy `_candidate_snapshot` byte-for-byte. Stage-2 deletes the
legacy snapshot handoff and makes `qc._armed` the sole carry, with the intraday entry firing via
`entry_trigger`. M1 design: **behavior CHANGES by design (parity NOT expected)** — the stub
entry_trigger replaces the gap-confirm; the real confirm is M3.

## Current (legacy) flow
- **Daily** (`_on_after_close_decision` → `decide_daily`, :1063): day chain runs → `winners` →
  `_capture_candidate_snapshot(winners)` (:1088) builds `_candidate_snapshot` AND the Stage-1 `arm`
  phase writes `qc._armed` + `_assert_arm_parity`.
- **Intraday** (`on_data` :980 → :1015): `_inject_intraday_candidates(ictx)` seeds the standing
  candidates FROM `_candidate_snapshot` into `bar_state` → `engine.on_intraday_bar(ictx)` runs
  `entry_selection` (PreFlightStaleness + BctIntradayGapVolConfirm, open-30m window) → `entry_timing`
  (ConfirmedMarketEntry) → `sizing` (intraday) → FIRE_ENTRIES.

## Target (two-clock) flow
- **Daily**: day chain runs → `arm` phase writes `qc._armed` (the ONLY carry). NO `_candidate_snapshot`.
  No FIRE on the daily clock (already true — FIRE_ENTRIES is intraday).
- **Intraday** (`on_data`): `entry_trigger` (StubEntryTrigger — reads `qc._armed` DIRECTLY, proximity-
  gated, un-windowed) → `intraday_sizing` (StubIntradaySizer) → FIRE_ENTRIES. No inject step (the
  trigger reads `_armed` itself). FIRE_ENTRIES evicts the fired sym from `_armed` (committed 5b609ff).

## DELETE (lean_entry + config)
1. `_capture_candidate_snapshot` (:1226-1304) + the `self._candidate_snapshot` state (:413).
2. `_inject_intraday_candidates` (:1349-1390) — the snapshot→bar_state seed (entry_trigger replaces it).
3. `_assert_arm_parity` (:1096) + the Stage-1 call (:1095) — its job (prove arm==snapshot) is DONE;
   with snapshot deleted there is nothing to compare. `arm` is now the sole truth.
4. `self._entry_confirm` (:415) + its clear (:1557) — the deferred gap-confirm progress store (legacy).
5. The **open-30m window** in `bct_intraday_gap_vol_confirm` (window_bars/window_closed) — superseded
   by the un-windowed entry_trigger (the deferred delete-2).
6. Champion config: swap `entry_selection`(PreFlight+GapVol) + `entry_timing`(ConfirmedMarketEntry) →
   `entry_trigger`(StubEntryTrigger) + `intraday_sizing`(StubIntradaySizer). (The gap-confirm logic
   becomes an M3 entry_trigger module — not deleted from the repo, just unwired from the M1 champion.)

## REWIRE (the _candidate_snapshot dependents → _armed)
- The rotation `_position_meta` stamp hook (:1337-1341 reads `_candidate_snapshot.get(sym)` for the
  entry thesis) → read `qc._armed.get(sym)` ({zone, daily_kijun, armed_date}).
- The `_signal_for_entry` / staleness reads (:1187, :1322) → `_armed` or delete (the staleness gate is
  part of the legacy confirm; the stub trigger doesn't need it — confirm with HQ).
- The #276b-1 FUNNEL stages that key off snapshot survivors → re-point to the `_armed`/entry_trigger
  survivor sets, or retire the legacy intraday stages (preflight_pass/gap_eligible/confirm_fire) since
  those phases are unwired. Observe-only — no trading impact; lowest priority.

## KEEP (the 5-min feed — the intraday tick source)
`Resolution.MINUTE`, `on_data` bar feed (:994-1009: `_intraday[sym]` intraday_tenkan/vol_window/
last_close/last_bar update), `_seed_intraday`, the after-close scheduled event (now arm-only).

## Behavior change + validation (M1: parity NOT expected)
Old champion: ~16 names confirm via gap+vol, ~20 via the deleted MOO 2nd-slot. New: candidates ARM on
the daily tick, fire via the stub entry_trigger (proximity to zone) per-bar, ZERO EOD/MOO fills. Gate
(M1 design, NOT parity): (a) day-chain arms candidates, (b) 5-min entry_trigger fires them across the
day, (c) ZERO 15:51/MOO fills (the #382 path gone — already true post delete-1), (d) per-phase
behavioral tests on dummy bars. A smoke BT shows the fire-time histogram spread across the day, none at
15:51.

## Proposed SUB-STAGING (reviewable pieces, each its own commit)
- **2a** — REWIRE the rotation hook + any hard `_candidate_snapshot` reader to `qc._armed` (additive-safe;
  snapshot still built). Tests green. [no behavior change]
- **2b** — SWITCH the champion intraday chain: config entry_trigger/intraday_sizing; `on_data` drops
  `_inject_intraday_candidates`; on_intraday_bar now runs the trigger chain. [behavior CHANGES]
- **2c** — DELETE the now-dead legacy: `_capture_candidate_snapshot`, `_candidate_snapshot`,
  `_inject_intraday_candidates`, `_assert_arm_parity`, `_entry_confirm`, the open-30m window. Tests green.
- **2d** — SMOKE BT (q1, local minute): confirm arms→fires-across-day→zero-15:51. Post the histogram.

## OPEN QUESTIONS for HQ
1. The PreFlightStaleness gate (staleness of the armed thesis) — keep as a day-phase `invalidation`
   slot, fold into `arm` (drop-on-thesis-break), or drop for M1 (stub)? Spec wants thesis-break drop on
   the daily tick — I lean: `arm` already rebuilds fresh daily (= implicit staleness); drop PreFlight for M1.
2. StubEntryTrigger proximity `near_pct` default — what zone-proximity fires the stub? (M1 stub value;
   M3 real trigger owns the real condition.) Propose 1% for the smoke.
3. Is the #276b funnel worth re-pointing for M1, or retire the legacy stages now (observe-only)?
