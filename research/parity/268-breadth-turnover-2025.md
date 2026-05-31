# #268 BREADTH/TURNOVER — Localized (diagnostic only, no fix)

**Date:** 2026-06-01 · **Branch:** feat/243-emit · **Track A (core-arch parity)**

**Inputs (every number below is from a real order artifact):**
- CLOUD: `research/parity/artifacts/cloud-orders-243.json` — backtest `8ddbe2b449df87edba5d3fd50b48bea1`, 291 orders (286 filled, 5 invalid/status-7), trio −0.683 / −9.05% / 291.
- LOCAL: `algorithm/v2_champion_asis/backtests/2026-05-31_23-36-54/1158674033-order-events.json` — the #265 run, 244 submitted / 243 filled.
- Diff script: `research/parity/diff_268_breadth_turnover.py` (mypy --strict clean). Captured output: `research/parity/artifacts/268-breadth-turnover-output.txt`.

---

## TL;DR — the driver is (iii) NOT exit-turnover and NOT capacity

The leading hypothesis (i — same concurrent + faster cloud EXITS via earlier d_ichi/Kijun breach) is **REFUTED**. So is (ii — capacity differs). The breadth gap is driven by a **1-bar ENTRY-EXECUTION offset at the order-fill layer**:

> **Cloud submits its NEW ENTRIES at the bar OPEN (04:00/05:00Z = midnight ET) and fills them the SAME trading day. Local submits ALL orders at the bar CLOSE (20:00/21:00Z = 16:00 ET) and fills them the NEXT trading day. All 58 of cloud's open-bar submissions are buys (entries); local has ZERO open-bar submissions.**

Cloud's entries execute one bar earlier than local's. That 1-bar lead shifts cloud onto a different position date-grid: it occupies slots one bar sooner, frees them one bar sooner, and re-ranks the universe against a shifted calendar — yielding a wider, more-rotated symbol set. This is an **execution-timing / daily-bar-emission** divergence, **not** an indicator, regime, exit-stop, or sizing divergence.

**The #268 fix target is the ENTRY execution / daily-bar fill-timing path — NOT the daily d_ichi exit path.** The exit path is clean (proven below: 56/61 same-entry round-trips exit on the identical date).

---

## 1. Concurrent-holdings — SAME ~cap (confirms same capacity)

Reconstructed held-position count per day from buy/sell fills, both sides:

| metric | CLOUD | LOCAL |
|---|---|---|
| max concurrent | **20** | **20** |
| median concurrent (trading days) | 11 | 10 |
| open at BT end | 10 | 9 |

Max concurrent is **identical (20)**, median essentially identical (11 vs 10). Same sizer (FlatPctHeatcap, position_pct=0.10), single code path → **same capacity**. Hypothesis (ii) refuted: cloud does NOT hold more concurrent positions. (Note: the heat-cap admits ~20 concurrent, not ~10 — the position_pct=0.10 floor is not the binding concurrency limit; both sides hit the same ceiling.)

## 2. Turnover / hold-duration — essentially IDENTICAL

| metric | CLOUD | LOCAL |
|---|---|---|
| filled orders | 286 | 243 |
| buys / sells | 148 / 138 | 126 / 117 |
| round-trips (entries) | 148 | 126 |
| closed round-trips | 138 | 117 |
| **median hold (closed)** | **16.5 d** | **20 d** |
| mean hold (closed) | 23.0 d | 24.2 d |
| distinct symbols | **111** | **93** |
| distinct trade DATES | **101** | **91** |

Cloud's median hold is slightly *shorter* (16.5 vs 20) but mean is nearly equal (23.0 vs 24.2). This small gap is an artifact of the entry offset (below), not a faster exit engine.

## 3. Exit-timing — REFUTES the d_ichi-leads-on-cloud hypothesis

For the 74 symbols both traded, matching round-trips by **shared entry date** (within 2 trading days) gives 61 matched round-trips:

- **56 of 61 exit on the IDENTICAL date.** 4 cloud-earlier, 1 local-earlier.
- Median hold of matched trips: cloud 15 d vs local 16 d. Mean: 23.1 vs 24.7.

When cloud and local enter the same name on the same bar, they exit on the same bar. **The daily d_ichi / Kijun-G3 exit path is clean** — it is NOT firing sooner on cloud. The large per-name hold deltas seen in a naive "first round-trip per symbol" comparison (e.g. JPM cloud 1 d vs local 53 d) are an artifact of comparing *different episodes* — cloud's Jan-02 1-day episode vs local's Jan-03 53-day episode are different entries, separated by the entry offset, not the same trade exiting at different times.

## 4. Entry breadth — the gap is at the ENTRY date-grid

- Cloud entered 111 distinct symbols, local 93. Overlap 74. Cloud-only 37, local-only 19.
- Cloud trades on **101 distinct dates** vs local's **91**: 30 cloud-only dates, 20 local-only dates. The two rebalance/trade calendars are shifted, not identical.
- **18 symbols** cloud entered ONLY on a cloud-only date and never otherwise (e.g. AXP, C, HPE, JPM, MRVL, T, ET, NFLX, CRWD, SNOW…). These are names cloud picked up because its grid landed on a bar local's grid skipped.

---

## The root mechanism — order submission/fill timing

`engine.py` fires **every** order (entry and exit) via `qc.market_on_open_order(...)`. Data resolution is `Resolution.DAILY`. The divergence is purely in WHEN the daily bar arrives at `on_data` and therefore when the MarketOnOpen order fills:

| | submit time-of-day | fill latency (submit→fill) |
|---|---|---|
| **CLOUD** | 58 buys at **04:00/05:00Z** (midnight ET, bar OPEN) + the rest at close | **0 days: 53 orders**; 1 day: 184; 3: 46 |
| **LOCAL** | **0** orders at the open; all at 20:00/21:00Z (16:00 ET, bar CLOSE) | 1 day: 203; 3: 35; rest: 5 |

Local's daily bar is delivered at end-of-day (16:00 ET → submit at close → MarketOnOpen fills *next* day's open). Cloud's daily bar is delivered at start-of-day (midnight ET → submit at open → MarketOnOpen fills the *same* day's open). The close-submitted orders match between the two (20:00/21:00Z histograms are near-identical, including the DST shift); the divergence is the **58 cloud open-bar entry submissions that local lacks**.

### Concrete same-name example (the canonical case)

**Both compute the same first rebalance.** Local's own log: `2025-01-02 16:00:00 REBALANCE|2025-01-02|open=0|new_entries=10|exits=0`. But execution diverges:

- **CLOUD — C (Citigroup):** entered (submitted+filled) **2025-01-02**, exited **2025-01-03** → hold **1 day**. Cloud's MarketOnOpen filled at the Jan-02 open, then the Jan-03 re-rank dropped it.
- **LOCAL — C:** the same Jan-02 16:00 rebalance submitted the buy at 21:00Z Jan-02, but it **filled at the Jan-03 open** and was held to **2025-02-24** → hold **52 days**.

Same decision bar, but cloud is one fill-bar ahead: it enters Jan-02, re-evaluates Jan-03 and rotates out; local doesn't even hold C until Jan-03 and then parks it for ~7 weeks. Identical pattern for JPM (cloud 1 d vs local 53 d), HPE, T, UAL — all five names cloud bought Jan-02 and sold Jan-03 while local bought Jan-03 and held.

The first-bar instance is the cleanest, but the 30 cloud-only vs 20 local-only trade dates across the whole year show the offset cascades: every rotation lands cloud on a slightly different date-grid, compounding into 18 extra distinct symbols and 43 extra fills.

---

## Gap attribution

The **43-fill** gap (286 vs 243) and **18-symbol** gap (111 vs 93) are explained by the entry-execution offset:
- **58 cloud open-bar entries** that local executes one bar later. These create extra short-lived round-trips (53 same-day fills) and seed the cloud-only date-grid.
- Same max-concurrent (20) and same matched-trip exit dates (56/61) rule out capacity and exit-turnover. What's left is the entry-fill timing — it accounts for the entire breadth/turnover residual.

## What still needs the cloud chart

The order artifacts fully localize the mechanism — **no cloud chart is strictly required** for the breadth finding. The open item is now CLOSED: the WHY is `Settings.DailyPreciseEndTime` (`self.settings.daily_precise_end_time`) — LEAN delivers a daily bar to `on_data` at **market close (True)** or the **following midnight (False)** (QC docs, *OnData Method Timing* / *Time Frontier*). We set it NOWHERE (grepped src/build/algorithm → 0 hits), so each engine uses its own default: LOCAL = market-close (16:00 ET) delivery; CLOUD = midnight (00:00 ET) delivery. Proof in the order artifacts: cloud's Jan-02 C/JPM/HPE/T/UAL carry `createdTime=2025-01-02T05:00:00Z` (= 00:00 ET, day OPEN) and `lastFillTime=21:00:00Z` (same-day fill); local's same names `submitted 21:00:00Z` (16:00 ET, close) and `filled` Jan-03. Whole-FY histogram: **60 cloud submissions at 04:00/05:00Z (midnight ET) that LOCAL has ZERO of** — that bucket is the entire divergence. Full mechanism + the both-direction fix spec: **`research/parity/268-fix-spec.md`**. The `cloud-indicators-243.json` capture is orthogonal — it covers the already-clean signal path, not this execution path.

**Two-rebalance-tick (16:00 + 16:15) verdict:** the second daily tick is the **VIX CBOE index** daily bar (`Index-usa-VIX` is on Central Time in the market-hours DB; its 15:15/16:00 CT close maps to 16:15 ET, a separate timeslice from the 16:00-ET equity close). `on_data` fires on any data slice and runs the full engine unconditionally → the engine rebalances TWICE per day and submits two entry batches. **Benign for #268 parity** (the second tick exists identically on BOTH sides — cloud also shows the 20:15/21:15Z bucket), but it IS a genuine intra-day double-submit and should be tracked as its OWN item (gate `on_data` to once-per-day / the equity slice). Not in scope for the grid decision; flagged for Falk. Detail in `268-fix-spec.md` §D1.

---

## METHODOLOGY QUESTION — FOR FALK (the #1 morning item)

**HQ HELD the #268 fix.** It is not a bug to patch — it is a **fork in what counts as ground truth for
execution timing**, and the answer flips the #262 baseline. Decision needed before any apply.

### The two execution grids, stated plainly
- **LOCAL** = decide on the **EOD close of day T**, fill at the **open of T+1** (scan-after-close,
  buy-next-session). LEAN delivers local's daily bar at **market close (16:00 ET)**; the MarketOnOpen
  order fills the next session's open. **This is how George actually trades BCT** — the day's Ichimoku
  is only complete at the close, he scans then, and buys the following open. No look-ahead.
- **CLOUD** = decide at the **open of day T** on **prior-close (T-1) data**, fill at the **open of T**
  (one bar earlier, on staler decision data). LEAN delivers cloud's daily bar at **midnight (00:00 ET)**;
  the MarketOnOpen fills that same day's open. Cloud is **exactly one fill-bar ahead** of local.

Root knob: `Settings.DailyPreciseEndTime` — `True`=market-close delivery (local), `False`=midnight
delivery (cloud). We never set it; the two engines default differently. (Evidence: §"root mechanism"
above + `268-fix-spec.md` §D1.)

### The stakes — a 12.67pp swing
LOCAL **+3.62%** (244 orders / 93 symbols / Sharpe −0.139) vs CLOUD **−9.05%** (291 / 113 / −0.683).
**Which grid is ground-truth decides the #262 baseline.** Same code, same data, same config — the only
difference is *which bar the daily candle is handed to `on_data` on*, and it is worth 12.67 points of
return.

### THE INVERSION — surface it, do not assume cloud is right
The charter says "cloud = ground truth." **For execution timing that premise may be backwards.** If
LOCAL is George's faithful model (decide after close, buy next open — which it is), then **LOCAL is
ground-truth and CLOUD is the optimistic artifact**: cloud acts one bar earlier, capturing day-T's open
move that a decide-after-T's-close trader could not have traded until T+1. Under that reading #262
should **re-baseline to LOCAL (−0.139 / +3.62% / 244)** and treat cloud's −9.05% as a mis-executed
(too-early) grid — **NOT** force local→cloud. Do not reflexively chase the cloud number; on execution
timing the cloud grid is the one that looks like look-ahead-lite.

### The decision Falk needs to make
**Is the canonical execution grid LOCAL (decide-EOD-T, fill-open-T+1) or CLOUD (decide-open-T, fill-open-T)?**

- **If A — cloud is canonical:** apply `daily_precise_end_time=False` in the LOCAL entry → local
  converges to cloud (−9.05% / 291 / 113); #262 baselines to cloud. Cost: **every recorded champion BT
  is invalidated → full re-baseline.** (Spec: `268-fix-spec.md` §D2-A. Confirm: 1-wk local BT, submit
  times must move to 04:00/05:00Z.)
- **If B — local is canonical (the faithful BCT model):** #262 baselines to LOCAL (+3.62% / 244 / 93);
  the cloud deploy (`qc_v2_cloud`) gets `daily_precise_end_time=True` to match (or is quarantined as a
  known-divergent venue). Lower blast radius — a deploy setting + a baseline ruling, no champion-logic
  change. (Spec: `268-fix-spec.md` §D2-B. Confirm: cloud BT, created times must move to 20:00/21:00Z.)

Both knobs are the same documented one-liner, applied on opposite sides. **Recommended framing:** B is
the faithful-model reading and the lower-risk path; A only if Falk rules the cloud venue is the
ground-truth contract regardless of BCT semantics. **Decision is binary and decision-ready.**

## Constraints honored

Diagnostic only. champion/dist/src untouched. RAW order data only. mypy --strict clean; `python3 -m pytest -q` → **606 passed**.
