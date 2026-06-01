# #276b Plan — Intraday Execution Model (the GH#25 P&L unlock) — PLAN, NO CODE YET

**Status:** PLAN for HQ review (docs/plan-first per charter; Phase 0 was docs-first for this reason).
**Branch/worktree:** feat/276b-intraday-model @ mainV2 0bed8df (off the merged #276a fire seam).
**Parent:** #270 P4 / #276. Ticket: #310. **SOLO** (core architecture — no workers).
**Scope:** the intraday EXECUTION phases — the real P&L model. The daily SIGNAL stack is unchanged.

---

## 0. What already exists (the substrate — do NOT rebuild)

- **#276a fire seam (merged 0bed8df):** `OrderIntent.order_type` dispatch (market_on_open|market|stop_market|limit); ONLY FIRE_* touches the broker. `#290` GTC protective stop placed + tracked + cancelled-on-exit at FIRE_ENTRIES. GUARD-1/2/3 fail-loud on trim/add/re-entry with a live stop. `#181` commit-aware gross cap.
- **#275 intraday DATA pipeline (merged):** `qc._intraday[sym] = {intraday_tenkan, vol_window, last_close, last_bar}` fed DIRECTLY by 5-min ("minute") bars in `on_data` (no consolidator — Massive is natively 5-min). `qc._intraday_active` = candidates∩CAP + holdings with a live 5-min sub. **Intraday Tenkan period is in 5-min-BAR units** (Tenkan(9) ≈ 45 min). These are the GH#25 confirm inputs the entry phase reads (single code path, O(1)/candidate, NO per-bar history).
- **Two-clock engine (#274):** `on_daily_bar` (decision) + `on_intraday_bar` (execution). `_partition_clocks` routes each phase by `PHASE_RESOLUTION`; **FIRE_ENTRIES follows entry_timing's clock** → tagging the entry phases `intraday` auto-routes firing to the intraday clock. No engine-loop change needed.
- **Contracts already specced:** PHASES.md §5/§6/§11/§15/§20, ARCHITECTURE.md §10. This plan builds TO them.
- **Daily proxies present, to RETIRE as champion phases:** `BctEntryConfirm` (#253 daily §4 Gate-2, −1.016 proxy) and `MarketOnOpenEntry` (blind next-open). Kept as fixtures/reference only.

## 1. The model (PHASES.md §5/§6/§15, GH#25 §3)

Daily signal picks WHICH names (close T → candidate list + snapshot for T+1). On T+1, on completed 5-min bars: pre-flight-validate → confirm intraday → fire `market` → rest a GTC protective stop → exit intrabar on a `stop_market` cross. NO blind open.

## 2. Phases to BUILD (impl → contract → mechanic)

### 2a. `PreFlightStaleness` (entry_selection sub-role 1, intraday, FIRST) — NEW
- **Mechanic (ASYMMETRIC — HQ correction, grounded in BCT-6):** George's entries have MEAN GAP **+5.1%**, 85% trend UP — gap-UPS are the NORM, not staleness. A symmetric "reject any gap > X%" would KILL his bread-and-butter entries. So the gate is asymmetric:
  - **INVALIDATE** on gap-DOWN / close BELOW daily Kijun (thesis broken).
  - **ALLOW** gap-UPS within a GENEROUS tolerance; bound only EXCESSIVE gap-up (chase).
- **Reads:** candidate snapshot (signal_price, daily_kijun) + current completed 5-min bar (`qc._intraday[sym].last_close`). NEVER T+1's daily bar.
- **Params:** `below_kijun_invalidates: bool = True`; `gap_up_tolerance_pct` (bounds EXCESSIVE gap-up ONLY, generous default; sweepable). No symmetric gap reject.
- **Output:** filters `sized_orders` in place; publishes invalidation reason to facts.
- **Test (required):** a +5% gap-up candidate is NOT invalidated; a gap-DOWN-below-Kijun candidate IS.

### 2b. `BctIntradayConfirm` (entry_selection sub-role 2, intraday) — NEW (the LOCKED mechanic)
- **Mechanic (GH#25 §3.2):** confirm on completed 5-min bars — **intraday-Tenkan reclaim + rising volume**, within the first ~2h window. Defer across intraday bars until confirmed OR the window closes (no-confirm-by-window-end → SKIP, never a blind fill — SG5).
- **Reads:** `qc._intraday[sym]` (intraday_tenkan, vol_window, last_close/last_bar) — maintained, O(1), no history.
- **Reclaim def (to confirm with HQ, §8 Q1):** completed-5-min close crosses from ≤ intraday_tenkan to > intraday_tenkan (a reclaim event), AND current 5-min volume > rising-volume gate (e.g. vol > mean(vol_window) × `vol_mult`).
- **Window:** first ~2h of RTH = first N completed 5-min bars (N≈24). Param `confirm_window_bars`.
- **Params:** `vol_mult`, `confirm_window_bars`, `tenkan_reclaim_tol`. space() = the swept axes.
- **Output:** `sized_orders` filtered to confirmed; per-symbol state on `qc._entry_confirm[ticker]`.
- **State (SG9):** the deferred-confirm progress + the candidate list MUST clear at session end — T+1 starts clean, no bleed to T+2.

### 2c. `ConfirmedMarketEntry` (entry_timing, intraday) — NEW (baseline)
- **Mechanic:** once confirmed, set `intent.order_type="market"` (fire immediately intraday), NOT next-open MOO. Pass-through that stamps order_type; the seam fires.
- **Params:** none (baseline). Phase-2: BuyStopEntry/LimitPullbackEntry rewrite price/stop.

### 2d. `stops_initial` impl (e.g. `swing_low_initial` or `kijun_initial`) — NEW/verify
- **Mechanic:** compute the INITIAL protective level (swing-low or daily Kijun) and set `intent.protective_stop` so the #276a seam places the GTC catastrophic floor on FIRE_ENTRIES.
- **Note:** the seam already FIRES + tracks + cancels the GTC stop (#290). This phase SETS the level. Without it the champion fires no protective floor.
- **Params:** `lookback` (swing_low) or none (kijun).

### 2e. `kijun_g3` exit_hard → intraday stop-market (adapt existing)
- **Mechanic (GH#25 §3.3, PHASES §15):** stop LEVEL from daily structure (Kijun / G3 cloud-bottom — the existing kijun_g3 math, UNCHANGED), TRIGGER = intraday completed-bar cross. Emit `ExitIntent` with `order_type="stop_market", stop=<level>` → fires intrabar via the seam.
- **Change vs today:** the existing `kijun_g3_exits` emits exit_intents that fire MOO (daily). #276b: tag exit_hard `intraday`, emit `order_type=stop_market`. Stop math untouched (parity-preserved); only the order TYPE + clock change. RETIRE the daily-close<Kijun→MOO behaviour.

### 2f. Cancel-replace protective-stop lifecycle (folds in #310 GUARD work)
- Resize/replace the #290 GTC stop on trim/add (so a trim doesn't over-sell, an add isn't under-protected) → LIFT the #276a GUARD-1/2 fail-loud blocks once safe, mutation-verified.
- **GUARD-3 tighten (HQ pal/Gemini finding):** fire the re-entry guard whenever `_prior` has a live `protective_stop_ticket`, regardless of the new intent's `protective_stop` (today it slips when protective_stop=0 → orphan). Fix here.

## 3. Wiring (two-clock + fire seam)
- Tag 2a/2b/2c `PHASE_RESOLUTION="intraday"`, 2e exit_hard `intraday`. `_partition_clocks` then routes them + FIRE_ENTRIES/FIRE_EXITS to `on_intraday_bar` automatically.
- **Daily→intraday SNAPSHOT handoff (BUILD/VERIFY):** the daily clock must publish each candidate's snapshot (signal price, daily Kijun) and the standing candidate list, surviving to T+1's intraday ticks then CLEARED at session end (SG9). Verify #274/#275 plumbing carries this; build the snapshot field if absent. **Likely the biggest net-new wiring item.**
- **SG8:** the daily clock fires ZERO orders (decision only). Assert no FIRE_* on the daily subset for the champion.
- champion_intraday config ASSEMBLY + re-baseline = #277 (NOT #276b). #276b delivers the phases + unit/integration wiring + a smoke config to exercise them.

## 4. Look-ahead safety (the #268 lesson — CONVENTIONS §Look-ahead)
- Consume only COMPLETED 5-min bars (the maintained `qc._intraday` last_* are completed-bar state).
- The T+1 intraday path NEVER reads T+1's daily bar (embeds the close = look-ahead).
- `history()` (if any) ends strictly before `self.time`.
- **Fail-loud negative test:** assert the engine does NOT act on a forming/future bar (SG3/SG7).

## 5. Tests (every phase: behavioral + fail-loud + outage, mutation-bite — the testing pillar)
- **Per phase:** real(istic) 5-min bar inputs → assert the decision (confirm fires on reclaim+vol; pre-flight invalidates a gapper; exit fires on the intraday cross; ConfirmedMarketEntry stamps market); fail-loud on degraded/cold intraday indicator / missing 5-min bar; outage (cold intraday feed → crash-not-mirage).
- **Safeguard suite (ARCHITECTURE §11.1):** SG3 (no look-ahead), SG4 (pre-flight invalidates a gapper), SG5 (confirm→enter; no-confirm-by-window-end→skip, no blind fill), SG6 (intraday stop-market exit), SG7 (completed-bars-only), SG8 (zero fills on daily clock), SG9 (no state bleed across sessions). Each mutation-verified to BITE.
- **Two-clock state-handoff:** candidate list + snapshot persist daily→intraday correctly; cleared at session end.
- **Cancel-replace:** trim/add resizes the stop (no orphan / no under-protection); GUARD-3 tightened + tested; GUARD-1/2 lifted only where safe.
- **Real-data G-DATA:** the real confirm/exit path over real conformed 5-min data across warmup+FY (the #260 FakeQC gap; CI runs WITH data, no green-by-skip).

## 6. Dependencies / prereqs
- **#306** (two-clock `_tick_entry_value` same-clock invariant) — gross-cap commit-awareness assumes entries+adds same-clock; resolve before/with this (entries+adds both intraday here → likely fine, but close #306 explicitly).
- **Snapshot handoff plumbing** (§3) — verify/build first; everything intraday depends on it.
- **#275 intraday state** — confirm `qc._intraday` is populated + warm for candidates on T+1 (smoke-verify).
- **#309 fast-follow** (hasattr fail-loud) — independent; land whenever.
- Downstream: **#277** champion_intraday assembly + local≈cloud re-baseline (the TRUE baseline) consumes these phases. **#276c** (if split) = champion config.

## 7. Proposed build sequencing (each sub-unit = its own dance: src commit → dist rebuild → 3-gate → code-review → PR --no-ff)
1. **276b-0 (enabler):** snapshot daily→intraday handoff + SG8/SG9 state-clear plumbing + a two-clock smoke (de-risk the #268-analogue on the intraday clock BEFORE the model). Verify #275 state warm.
2. **276b-1:** `PreFlightStaleness` + `BctIntradayConfirm` (entry_selection intraday) + `ConfirmedMarketEntry` (entry_timing) + SG3/4/5/7/9 tests.
3. **276b-2:** `stops_initial` level-setter + `kijun_g3` → intraday stop-market exit (SG6) + cancel-replace lifecycle + GUARD-3 tighten / GUARD-1/2 lift (#310).
4. **Hand to #277:** champion_intraday config + re-baseline (separate ticket).
Rationale: enabler first (handoff is the load-bearing risk), then entry, then exit+lifecycle. Behavioral+fail-loud+outage per sub-unit. code-reviewer + HQ second-model pass each PR.

## 8. HQ RULINGS (LOCKED 2026-06-01, grounded in BCT-6/BCT-7 George-entry analysis)
- **Q1 — confirm mechanic, LOCKED:** Reclaim = completed-5-min close CROSSING ≤→> intraday_tenkan (a cross EVENT, not merely "above" — don't fire an already-extended name). Rising volume = current completed-5-min vol > mean(vol_window) × `vol_mult` (NOT strictly-increasing — 5-min vol too noisy); `vol_mult` default ~1.5, swept 1.2–2.5. Grounding: BCT-6 lower_wick_rejection entries = best 81.1% WR / +8.0% mean P&L (dip-then-reclaim + volume = George's winning shape).
- **Q2 — window, LOCKED:** `confirm_window_bars` = first ~2h = N≈24 completed 5-min bars as the OUTER bound (sweepable; BCT-6: 95.7% of entries in open_30m → mass is EARLY, 2h is the safe cap). No-confirm by window-end → SKIP for the day, NO T+2 carry (SG9).
- **Q3 — stops_initial = DAILY KIJUN, LOCKED.** The #290 GTC catastrophic floor sits BELOW intraday noise (fires only on a true gap/outage, not chop; no collision with the kijun_g3 runtime exit). swing_low too tight → premature catastrophic fills → a later sweep variant, NOT the champion default. Parity with existing Kijun math.
- **Q4 — snapshot handoff:** do NOT assume present. EMPIRICALLY VERIFY in 276b-0 (HQ lean: net-new — the daily-only engine never forwarded a snapshot). Report the finding before 276b-1.
- **Q5 — scope, CONFIRMED:** #276b = phases + wiring + smoke; champion_intraday assembly + full local≈cloud re-baseline = #277.

## 8b. PARKED (do NOT scope-creep into 276b-1)
- `lower_wick_rejection` as an entry-QUALITY signal (BCT-6 81.1% WR) → a Phase-2 entry_timing variant / #305 sweep axis. Noted, not built now.

## 9. Risks (eyes-open, ARCHITECTURE §13)
- Snapshot/state handoff across the daily→intraday boundary (SG9 bleed) — the subtle correctness risk.
- Intraday delivery parity local vs cloud (the #268-analogue on the 5-min clock) — smoke-BT before the full build (276b-0).
- Confirm-window edge cases (gap at open, thin-volume name, no completed bar yet) — fail-loud, never permissive (the GH#25 §3.2 "return True on insufficient data" is RETIRED → loud-skip).
- Cancel-replace stop lifecycle correctness (orphan/under-protection) — the real-money lifecycle bug class; mutation-verify hard.
