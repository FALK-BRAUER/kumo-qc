# #276 Build Plan — the GH#25 intraday model (THE big one) — CHECKPOINT

**Status:** #275 (data + subscription lifecycle) MERGED (PR #295, mainV2=1ab0400). #276 is the
largest, highest-stakes ticket — the intraday clock finally FIRES ORDERS, 5 distinct components,
the first capture of George's validated +5.81% intraday alpha. Checkpointed for a FRESH focused
build (the #275b fresh-context call was right; this is bigger — same discipline, harder).

## GATE 0 — CLOUD-VERIFY THE #275b PLUMBING FIRST (before building phases on top of it)
HQ flagged 3 items unverifiable locally (LEAN daily/minute resolution-binding). ONE cloud BT +
log-grep at the START of #276 closes all three — do this BEFORE the phase build:
1. **Daily indicators stay DAILY for an overlapping name:** adding a MINUTE sub to a
   universe-held-DAILY name must NOT rebind its daily Ichimoku/SMA/ADX to MINUTE. Grep the cloud
   log: the daily indicator values for an intraday-subscribed name == a pre-#275b run's values.
2. **UNSUBSCRIBE fully drops the feed:** `remove_security` on an intraday name actually tears down
   (add_equity flipped a universe security to user-added → confirm full teardown, no dangling).
3. **The 624-bar seed drives is_ready** (fill-forward-OFF / genuine 5-min spacing — the #277 flag,
   pulled forward since #276 is the first consumer).
If any FAILS → fix the #275b plumbing before the phase build (don't build on a broken substrate —
the #268 lesson). Build the #275a 5-min data first if not present:
`python3 scripts/build_minute_from_parquet.py --start 20230620 --end 20251231 [--tickers <test set>]`

## The 5 components (all REQUIRED before champion_intraday #277)
1. **entry_selection — intraday confirm (`BctIntradayConfirm`)** + **pre-flight staleness gate**
   (`PreFlightStaleness`, runs FIRST). PHASE_RESOLUTION="intraday".
   - Pre-flight: re-validate each candidate vs its daily SNAPSHOT (signal price, daily Kijun) — if
     T+1 gapped away/below the thesis → INVALIDATE (George's gap-up discipline; SG9 no-stale-bleed).
   - Confirm: intraday-Tenkan reclaim + rising volume on the COMPLETED 5-min bar (the `_intraday`
     suite from #275b: intraday_tenkan + vol_window), within ~first 2h. GH#25 §3.2. The #253 daily
     Gate-2 is RETIRED (proven-wrong proxy). Reads `qc._intraday[sym]`; fail-loud if not-ready
     (no silent cold-score — DegradedDataError, mirror the daily guard).
2. **entry_timing — `ConfirmedMarketEntry`** (PHASE_RESOLUTION="intraday"): on confirm, emit an
   OrderIntent with `order_type=market` (fire immediately intraday) — NOT next-open MOO.
3. **exit_hard — intraday stop-market** (PHASE_RESOLUTION="intraday"): the Kijun/G3 stop LEVEL
   from daily structure, fired as an intraday `stop_market` OrderIntent (intrabar, not next-open).
   This is the INTELLIGENT exit ON TOP.
4. **#290 — INITIAL PROTECTIVE STOP (GTC)**: a broker-side resting `stop_market` placed on
   FIRE_ENTRIES — the catastrophic floor UNDER the runtime exit, fires intrabar even on
   gap/outage/halt. DISTINCT from #3 (dumb safety net vs smart exit; BOTH, not either). Likely a
   new fire-seam behavior on FIRE_ENTRIES (place the protective stop alongside the entry fill).
5. **#181 — gross-exposure control**: portfolio_risk + gross_exposure_cap (% rule, NOT a count
   cap); the charter fail-loud (adds-without-cap → raise) already enforced in validate_invariants —
   wire the cap phase + confirm the structural invariant.

## The fire seam (#274 gave the OrderIntent.order_type seam — #276 USES it)
FIRE_ENTRIES/FIRE_EXITS must dispatch on `intent.order_type` (market / stop_market / limit) instead
of the hardwired market_on_open_order. This is the #274-forecast seam; #276 implements the dispatch.
The GTC protective stop (#290) is an EXTRA order placed at FIRE_ENTRIES (the entry + its resting stop).

## champion_intraday config (the #277 target, assembled here)
A NEW StrategyConfig wiring: universe(dv_rank_cap, daily) → signal(bct_score_full, daily →
signal_scores) → regime(daily) → ranking(daily) → entry_selection(PreFlightStaleness +
BctIntradayConfirm, intraday) → entry_timing(ConfirmedMarketEntry, intraday) → sizing → portfolio_risk
(#181) → exit_hard(intraday stop-market) + GTC(#290). NOT a fixture — passes the #272 gate
(entry+exit wired). champion_asis stays the retired fixture.

## Tests (per phase: behavioral + fail-loud + outage, mutation-bite; + the SG suite)
- entry-confirm: fires on Tenkan-reclaim+volume / declines without / fail-loud on cold intraday
  indicator (no silent cold-score). pre-flight: invalidates on gap-away, passes on thesis-intact.
- exit stop-market: fires intrabar on the level cross (completed bar), not next-open.
- GTC: placed on entry, resting, fires on gap even if runtime exit doesn't (the catastrophic floor).
- gross-cap: blocks entry beyond the cap; adds-without-cap → raise.
- SG9 no-state-bleed (intraday confirm state cleared at session end); look-ahead (completed bars only).
- Behavior: champion_intraday is a NEW measurement (NOT −0.139, NOT −0.683 — those were the MOO
  phantom); the #277 re-baseline establishes the TRUE local≈cloud on this model.

## Constraints
- config_hash: champion_intraday is a NEW config → its OWN hash (not e573e84b1ce1, which is the
  asis fixture). dist tracks the CHAMPION → once champion_intraday is the champion, dist builds it.
  (During #276 build, measure into dist_tmp; don't displace the asis-fixture dist until #277 cutover.)
- 2-commit dance for dist. Explicit git add. Read ~/reference/Lean for stop_market/GTC order APIs +
  the fire-seam (don't guess). No if-cloud, RAW, single path.
- This is multi-PR-worthy: consider splitting (a) the fire-seam + GTC + gross-cap (engine/risk),
  (b) the entry-confirm + pre-flight + stop-exit phases, (c) the champion_intraday assembly. HQ's
  call on the split at build time.

## After #276 → #277 (champion_intraday + re-baseline local≈cloud — the TRUE baseline) → #278
(SG suite) → #279 (closeout) → #281 (cutover mainV2→main).
