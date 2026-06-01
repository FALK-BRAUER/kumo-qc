# #275b Build Plan — dynamic intraday subscription lifecycle + indicator suite (CHECKPOINT)

**Status:** #275a (data builder + spacing guard + Option-C docs) MERGED (PR #289). #275b not yet
built — checkpointed here so a fresh context resumes instantly (HQ: "resume #275b with fresh
context"; it's the flagged highest-risk leak-prone piece — quality over speed).

## The reference facts (already researched, ~/reference/Lean @ 96a670a9 — DON'T re-guess)
- **`RemoveSecurity` does NOT auto-dispose user consolidators/indicators** (QCAlgorithm.cs:2575 —
  it only handles underlying/child/canonical securities). → explicit `remove_consolidator` +
  indicator cleanup on rotation is MANDATORY (the #213e leak is real).
- **Seed-on-subscribe:** `history(sym, N, Resolution.MINUTE)` → feed the intraday indicators, OR
  `warm_up_indicator`. The existing `_seed_daily`/`_seed_weekly` pattern (lean_entry.py:~480) is
  the template — seed ONLY post-warmup entrants (`if not self.is_warming_up`).
- **Option C (HQ-approved):** our Massive IS 5-min → subscribe `Resolution.MINUTE` (delivers our
  5-min bars), intraday indicators update DIRECTLY per 5-min bar — **NO consolidator** for the
  5-min layer (the data is already 5-min; a consolidator would double-bucket). Periods are in
  5-MIN-BAR units (intraday Tenkan(9) = 45 min).
- The existing `on_securities_changed` (lean_entry.py:393) already does explicit daily+weekly
  consolidator removal — EXTEND that exact pattern for the intraday teardown.

## Build steps (engine-core, solo, careful)
1. **State (initialize, ~line 228):** `self._intraday_indicators: dict[Symbol, dict] = {}` +
   `INTRADAY_SUBSCRIBE_CAP` constant (explicit, parameterized, logged — candidate+holdings only,
   never whole-universe = the #213e OOM scar).
2. **`_subscribe_intraday(sym)`:** `add_equity(sym, Resolution.MINUTE)` (RAW), build the intraday
   indicator suite (intraday Tenkan + volume — the GH#25 confirm inputs, on 5-min bars), register
   them, SEED from `history(MINUTE)` if `not is_warming_up` (avoid cold-DegradedDataError on the
   first 5-min bar). Store in `_intraday_indicators[sym]`.
3. **`_unsubscribe_intraday(sym)`:** explicit teardown — `remove_consolidator` (if any), unregister
   indicators, `del _intraday_indicators[sym]`, `remove_security(sym)` for the minute subscription.
   THE LEAK AVOIDANCE — mandatory per the reference fact above.
4. **Sync on the daily selection:** after `_coarse_selection` produces the daily candidate list +
   the daily selection runs, reconcile the intraday subscription set to (today's candidates ∩ cap)
   + current holdings; subscribe new, unsubscribe dropped. (The daily clock decides WHO gets an
   intraday subscription for T+1.)
5. **Route 5-min bars to `on_intraday_bar`:** `on_data` already routes daily → `on_data_with_ctx`;
   add the minute-slice path → build an intraday PhaseContext (clock="intraday") → engine
   `on_intraday_bar(ctx)`. (The engine method exists from #274; it's a no-op until #276 wires an
   intraday phase — so #275b can land with the plumbing live + the intraday clock still effectively
   dormant behavior-wise until #276.)

## Tests (mandatory — behavioral + leak + cold, mutation-bite)
- **LEAK test:** subscribe a candidate → drop it from candidacy → assert `_intraday_indicators`
  no longer holds it AND the consolidator/security removed (no accumulation across rotation).
- **COLD test:** a post-warmup entrant → assert seed-on-subscribe warms the intraday indicators
  BEFORE the first intraday score, OR the not-ready path is fail-loud (no silent cold-score).
- **CAP test:** candidate set > cap → only cap-many intraday subscriptions, logged.
- **Behavior-unchanged:** with no #276 intraday phase, on_intraday_bar stays a no-op → the daily
  champion behavior is still identical (the #274 invariant holds through #275b).
- Real-data integration: over the FY2025 5-min data (built by #275a's builder), the intraday
  indicators warm + the subscription set tracks candidates.

## Constraints
- champion behavior UNCHANGED until #276 wires a phase (the intraday clock is plumbing-live but
  phase-empty). config_hash unchanged. RAW. No if-cloud. Explicit `git add`. 2-commit dance for dist.
- #275a's 5-min data must exist locally to run the real-data test — build it first:
  `python3 scripts/build_minute_from_parquet.py --start 20230620 --end 20251231` (warmup+FY, the
  candidate names; or scope --tickers to the test set). ~heavy; the spacing guard will raise on any
  mislabeled day.

## After #275b → #276 (the GH#25 phases that CONSUME this):
intraday entry-confirm (Tenkan reclaim + volume) + pre-flight staleness gate + stop-market exit +
the #276 essentials HQ flagged: #290 GTC protective stop + #181 gross-exposure cap (both required
before champion_intraday goes live #277).
