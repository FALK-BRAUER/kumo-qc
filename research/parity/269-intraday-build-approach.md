# #269 — Multi-Timeframe Engine: Build-Approach Analysis (design-level, NO code)

Daily signal → intraday execution (GH#25, Falk-approved). Grounded in: the current v2 engine
(`src/engine/engine.py`), the GH#25 spec (`docs/notes/GH25_intraday_design_spec.md`), and
LEAN-idiomatic multi-timeframe patterns (Context7 / quantconnect/documentation).

## The key structural insight

`PHASE_ORDER` (engine.py:48-61) ALREADY splits cleanly along the two clocks:

```
DECISION (daily):   rebalance, filter, universe, signal, regime, ranking
EXECUTION (intraday): entry_selection, entry_timing, sizing, FIRE_ENTRIES,
                      stops_initial, trail, exit_*, FIRE_EXITS, adds, profit, trims
```

The daily phases pick WHICH names; the execution phases decide WHEN to fire on those names.
This is exactly GH#25's "daily signal / intraday execution" line — the phase taxonomy was built
anticipating it. The refactor is therefore a **tick-routing split**, not a re-architecture.

## Q1 — Two-clock tick model (RECOMMENDED + alternatives)

**RECOMMENDED: a per-phase RESOLUTION TAG + two engine entry points (one daily, one intraday),
both replaying the SAME PHASE_ORDER filtered by clock.**

- Add a `RESOLUTION` class attr to each phase (or a `PHASE_CLOCK` map in the engine): `daily` vs
  `intraday`. Default `daily` (every existing phase unchanged → champion-asis-class configs
  behave identically until an intraday phase is wired).
- Engine gets two methods:
  - `on_daily_bar(ctx)` → runs the daily-clock phases (signal/regime/selection/ranking) →
    produces the **candidate list + the daily decision state** (stored on qc, as today
    `_ranked_today`). Does NOT fire entries.
  - `on_intraday_bar(ctx)` → runs the intraday-clock phases (entry_selection/entry_timing/
    sizing/FIRE_ENTRIES/stops/trail/exit/FIRE_EXITS) against the standing candidate list +
    intraday bar. Fires orders.
- Wiring: the daily decision runs via a **scheduled event** (`schedule.on(date_rules.every_day,
  time_rules.before_market_close)` — the after-close scan Falk specified) OR on the daily
  consolidated bar; `on_data` (minute/5-min) routes to `on_intraday_bar`.

Why this over the alternatives:
- It preserves PHASE_ORDER as the single source of sequencing (no duplicate ordering logic).
- It's additive: a phase with no RESOLUTION tag = daily = today's behavior. champion-asis runs
  unchanged; only a config that wires an intraday entry phase activates the second clock.
- It maps 1:1 to the LEAN-idiomatic pattern (Context7): daily indicators on the daily
  subscription + a consolidator/scheduled-event for the execution timeframe.

**ALT-A — single on_data(minute) + an internal "is this the day's first/decision bar?" gate.**
Simpler wiring (one entry point) but re-introduces the exact day-boundary fragility that caused
the double-rebalance (VIX CT slice) + the #268 grid bug — the engine would re-derive "is it
decision time" from the clock each tick. Rejected: brittle, and it's how we got here.

**ALT-B — keep on_data(daily) for decisions + a separate scheduled intraday callback (GH#25 §3.4
11:00 rebalance).** Closest to GH#25 as written. Viable, but a fixed-time callback (11:00) is a
coarse proxy for "price confirmed above Tenkan intraday" — it checks confirmation only at 11:00,
not continuously. RECOMMENDED subsumes it (the intraday clock IS the continuous check).

## Q2 — Intraday subscriptions (RECOMMENDED)

**Dynamic: subscribe 5-min ONLY for the daily-selected candidates + current holdings, on T+1.**
- The universe is already dynamic (`add_universe(_coarse_selection)`); extend
  `on_securities_changed` / the selection to add a 5-min subscription for the ranked candidate
  set + held names, and REMOVE it when a name leaves candidacy/holdings.
- Whole-universe intraday = the #213e OOM scar (thousands × 78 intraday bars/day). Rejected.
- LEAN-idiomatic (Context7): `self.consolidate(symbol, timedelta(minutes=5), handler)` per
  subscribed name, or `add_equity(sym, Resolution.MINUTE)` scoped to the candidate set (GH#25
  §3.1 already specifies "only active candidates, not full universe"). Cap N (e.g. top-ranked +
  holdings) — an explicit, parameterized cap (per the implicit-caps charter), logged.

## Q3 — The non-MOO fire seam (RECOMMENDED)

**Make the fire seam HONOR the OrderIntent's order-type, set by the entry_timing/exit phase —
instead of the hardwired `market_on_open_order`.**
- Today FIRE_ENTRIES/FIRE_EXITS hardcode `qc.market_on_open_order` (engine.py:235,247,255,262).
  `OrderIntent` already carries `price`/`stop` fields (currently unused for entries).
- Extend OrderIntent with an `order_type` (market_on_open | stop_market | limit | market) +
  use its `price`/`stop`. The `_fire` seam dispatches on `intent.order_type`:
  `stop_market_order(sym, qty, intent.stop)` / `limit_order(...)` / `market_order(...)`.
- The entry_timing phase (the GH#25 confirmation) SETS the order_type+price (e.g. on intraday
  Tenkan-confirm → `market` immediately; or stop_market at the §4 Gate-5 day-type level). The
  MarketOnOpenEntry docstring already forecasts this seam ("a future engine seam would honour
  the order type" — market_on_open_entry.py:24). This is the planned extension point.
- Exits: stop_market_order (GH#25 §3.3) so stops fire intrabar, not next-open MOO.

## Q4 — The 2nd (intraday) indicator suite + consolidator (RECOMMENDED)

**A parallel intraday-indicator dict, fed by a 5-min consolidator, coexisting with the daily suite.**
- Today `_register_indicators` builds daily+weekly (d_ichi/w_ichi/sma200/adx/roc13/macd/
  vol_sma20/tbounce) via daily + weekly consolidators (lean_entry.py:414-502). ADD an intraday
  block: the GH#25 entry-confirm needs an intraday Tenkan (9-period on 5-min) + (if §4 Gate-2)
  intraday MACD/volume.
- LEAN-idiomatic (Context7, confirmed): create the intraday indicator, a
  `TradeBarConsolidator(timedelta(minutes=5))`, `register_indicator(sym, ind, consolidator)`,
  and WARM it from `history(sym, N, Resolution.MINUTE)`. Independent warmup on the intraday clock
  — does NOT touch the daily warmup (560d) path.
- Coexistence: keep daily indicators keyed as today; add `_intraday_indicators[sym]` keyed
  parallel; dispose the 5-min consolidator in `on_securities_changed` alongside the daily/weekly.
- Scope intraday indicators to the SUBSCRIBED candidate set (Q2) — not the full universe.

## Q5 — Look-ahead safety on the intraday path (CRITICAL — this is what bit us)

**Rules, enforced + tested (the #268 lesson):**
1. **Consume only COMPLETED consolidated bars** — act in the consolidator's `data_consolidated`
   handler (fires on bar CLOSE), never mid-bar. A 5-min Tenkan must use the last *completed*
   5-min bar, not the forming one. (Context7 pattern: the handler receives `consolidatedBar` =
   a closed bar.)
2. **The daily decision uses only bars through T's close** → candidates for T+1; the intraday
   execution on T+1 uses only T+1 intraday bars up to the current completed 5-min bar. No
   crossing: the T+1 intraday path must NOT read T+1's daily bar (which embeds T+1's close =
   look-ahead — the exact class Falk flagged).
3. **`history()` calls must end strictly before `self.time`** (the forward-only guard, like the
   #213f/#259 daily-seed drop-rows->=today). Add the intraday analogue.
4. A FAIL-LOUD negative test: feed a forming/future intraday bar → assert the engine does NOT
   act on it (raises or skips-loud), never silently uses it. (Mandate-class.)

## Q6 — Biggest risk / unknown + GH#25 reuse

**Biggest risk: the daily↔intraday STATE HANDOFF + warmup cost, not the tick split itself.**
- The candidate list + daily decision state computed at T-close must persist to the T+1 intraday
  clock cleanly (today everything is recomputed per daily tick; now decision and execution are on
  different ticks/days). Stale-state bugs live here.
- Intraday warmup COST: warming a 5-min Tenkan for N candidates from `history(MINUTE)` each time
  the candidate set rotates — could be heavy. Needs the dynamic-subscription cap + measurement.
- **Parity re-confirm:** this is a champion-behavior change → the #262 baseline RESETS to the
  intraday-confirmed model (neither −0.139 nor −0.683). A fresh local+cloud parity pass on the
  NEW model is required — and the two-clock path must itself be parity-checked (does cloud's
  intraday delivery match local's? the #268 question recurs on the intraday clock — verify early).
- **Unknown to confirm:** does local `lean backtest` deliver 5-min consolidated bars at the same
  wall-time as cloud? (The #268 daily-delivery divergence may have an intraday analogue.) CONFIRM
  with a short two-clock smoke BT before the full build.

**GH#25 reuse:** the spec sketches the mechanics (minute subscriptions §3.1, Tenkan confirm §3.2,
stop-market exits §3.3, scheduled intraday rebalance §3.4) and is REUSABLE as the execution
recipe — BUT it predates the v2 phase engine (it's written against the legacy oracle's
`_rebalance`/`_check_all_entry_gates`). The v2 mapping is: §3.1→Q2 (dynamic subs), §3.2→the
entry_timing phase + Q4 intraday indicators, §3.3→Q3 fire seam, §3.4→Q1 intraday clock. Also: the
GH#25 `_tenkan_confirmed` returns True (permissive) on insufficient data — under Falk's fail-loud
mandate that must become a loud-skip/raise, NOT a silent permissive pass.

## Honest size read
DEEP engine change (new tick-routing concept + dual-timeframe indicator lifecycle + a non-MOO
fire seam + the fail-loud REQUIRED_PHASES gate from the ground-truth report). The phase taxonomy
already anticipates the split (entry_timing slot, OrderIntent.price/stop, the forecast seam), so
the phase layer is ~half-scaffolded; the engine tick-model + fire seam + dual-clock indicator
lifecycle is the load-bearing new work. Data is NOT a blocker (5-min Parquet 2021→2026 exists).
Recommend building behind a NEW strategy config (champion_intraday) measured against the asis
fixture — never mutating champion_asis in place — and a two-clock parity smoke BT FIRST (de-risk
the intraday-delivery analogue of #268 before the full build).
