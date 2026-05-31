# #268 FIX SPEC — the 1-bar entry-fill grid offset (BOTH directions, NO application)

**Date:** 2026-06-01 · **Branch:** feat/243-emit · **Track A (core-arch parity)**
**Status:** SPEC ONLY — HQ explicitly HELD the fix. This is a methodology fork for Falk (see
`268-breadth-turnover-2025.md` → "METHODOLOGY QUESTION — FOR FALK"). No champion/dist/src/config
change is made by this document. No BT was run — the order artifacts already prove the mechanism.

---

## Deliverable 1 — the mechanism, PINNED (evidenced + LEAN-doc-cited)

### The knob: `Settings.DailyPreciseEndTime` (`self.settings.daily_precise_end_time`)

LEAN delivers a **daily-resolution bar to `on_data` at one of two times**, controlled by a single
algorithm setting:

> "Once an algorithm reaches the EndTime of a data point, LEAN sends the data to the OnData method.
> … For **daily bars, it occurs at market close or midnight, depending on the DailyPreciseEndTime
> setting**."
> — QC docs, *Data Processing > OnData Method Timing* (single-page Writing-Algorithms)

> "The `DailyPreciseEndTime` property is a flag that defines if daily bars should have an end time
> that matches the **market close time (`True`)** or the **following midnight (`False`)**."
> — QC docs, *Set Algorithm Settings > Property: DailyPreciseEndTime*

> "LEAN transmits data to your OnData method once your algorithm reaches a data point's EndTime.
> … for daily bars, it's either market close or midnight based on your DailyPreciseEndTime setting.
> This mechanism establishes a 'Time Frontier' … The Time property … consistently reflects this."
> — QC docs, *Data Handling > Time Frontier*

Our code **never sets** `daily_precise_end_time` (grepped `src/`, `build/`, `algorithm/v2_champion_asis/`
— zero hits). So each engine takes its own default, and the two engines differ:

| | daily-bar EndTime delivered to `on_data` | `self.time` at the rebalance | MarketOnOpen entry fills |
|---|---|---|---|
| **LOCAL `lean backtest`** | **market close = 16:00 ET** (`DailyPreciseEndTime=True` behavior) | 16:00 ET (= 21:00Z winter / 20:00Z summer) | next session OPEN (T+1) |
| **QC CLOUD** | **midnight = 00:00 ET** (`DailyPreciseEndTime=False`/legacy behavior) | 00:00 ET (= 05:00Z winter / 04:00Z summer) | SAME session OPEN (T) |

### The order-artifact proof (the canonical 2025-01-02 names)

CLOUD (`research/parity/artifacts/cloud-orders-243.json`), entries for C / JPM / HPE / T / UAL:
```
createdTime = 2025-01-02T05:00:00Z   (= 00:00 ET, EST=UTC-5 → bar delivered at DAY OPEN/midnight)
lastFillTime = 2025-01-02T21:00:00Z  (= 16:00 ET → MarketOnOpen filled the SAME day's open)
→ then SOLD createdTime 2025-01-02T21:00:00Z, filled 2025-01-03 → 1-day hold
```
LOCAL (`algorithm/v2_champion_asis/backtests/2026-05-31_23-36-54/1158674033-order-events.json`),
the SAME names:
```
submitted 2025-01-02T21:00:00Z   (= 16:00 ET → bar delivered at MARKET CLOSE)
filled    2025-01-03T21:00:00Z   (next session open) → held to 2025-02-24 (~52 days)
```
Same decision bar, same names — cloud's bar arrives ~16h earlier (midnight vs prior-close) so cloud
submits at the open and fills T; local submits at the close and fills T+1. Cloud is **exactly one
fill-bar ahead**.

### Submission time-of-day histograms (whole FY2025) — the decisive aggregate

| time-of-day (Z) | what it is (ET) | LOCAL submits | CLOUD created |
|---|---|---|---|
| **04:00 / 05:00** | **00:00 ET — midnight / day OPEN** | **0** | **60** |
| 20:00 / 21:00 | 16:00 ET — equity market CLOSE | 180 | 183 |
| 20:15 / 21:15 | 16:15 ET — VIX index close (see two-tick) | 62 | 47 |

The **60 midnight-ET (04:00/05:00Z) cloud submissions are entries local has ZERO of**. That bucket
*is* the entire divergence (matches the doc's "58 open-bar buys"; 60 here). Everything else (the
16:00 and 16:15 buckets) matches between the two sides within vendor noise. So the breadth/turnover
residual reduces to one fact: **cloud's daily bar reaches `on_data` at midnight-ET, local's at
16:00-ET**, and that is governed by `DailyPreciseEndTime`.

### Why MarketOnOpen is NOT the cause (candidate (d), refuted)

`engine.py` fires **every** order via `qc.market_on_open_order(...)` (lines 235/247/255/262) on BOTH
sides — identical order type, single code path. A MarketOnOpenOrder fills at the **next market open
after submission**. The divergence is therefore *purely WHEN `on_data` fires* (which sets the
submission bar), not the order type:
- submit at **midnight-ET T** → next open is **T's open** → fill T (cloud)
- submit at **16:00-ET T** (after T's open already passed) → next open is **T+1's open** → fill T+1 (local)
Same order semantics, shifted submission instant → shifted fill grid. (Candidates (a) confirmed =
the daily-bar delivery time; (c) UniverseSettings/market-hours is a *contributor* only via the VIX
two-tick, below — not the entry offset.)

### The two-rebalance-tick (16:00 + 16:15) — VERDICT: benign for parity, real double-submit within a day

On ~247 of 247 trading days the LOCAL log shows TWO full rebalance ticks: `16:00:00` and `16:15:00`
(plus 3 days at 13:00 = early-close sessions). Both run the **entire** phase chain and **both submit
entries** (e.g. 2025-01-02: 16:00 submits CEG/KMI/META/TSM/MRVL/JPM/GS/SPOT/C/T; 16:15 submits a
*different* 10 — AXP/RBLX/DASH/KR/HPE/AZO/NET/EQT/EXPE/MCO → 20 entries that first day).

**Root cause:** the algorithm subscribes the **VIX CBOE index** (`add_index("VIX")`, lean_entry.py:236).
The market-hours DB (`data/market-hours/market-hours-database.json`) has `Index-usa-VIX` on **Central
Time** (`market 08:30–15:15`, `postmarket 15:15–16:00`). VIX's daily-bar close (15:15/16:00 CT) maps
to **16:15 ET**, 15 min after the equity close (16:00 ET). The equity daily bars arrive in the 16:00-ET
timeslice; the VIX daily bar arrives in the **separate 16:15-ET timeslice**. `on_data` fires on *any*
timeslice carrying subscribed data and **unconditionally runs the full engine** (`lean_entry.py:608-620`
— no "did the universe set actually change / is this the equity slice" guard), so the engine runs
**twice per day** and submits entries twice.

- **Benign for parity:** the second tick exists on **BOTH** sides identically (cloud also shows the
  20:15/21:15Z bucket: 47 orders; local 62). It is NOT a local-only artifact and does NOT drive the
  cloud↔local divergence — the divergence is solely the midnight bucket. The 268 finding stands.
- **But it IS a genuine intra-day double-submit** (two same-day entry batches off two slightly
  different data slices). It is orthogonal to #268 and should be tracked as its own item: the engine
  arguably should rebalance **once per day** (gate `on_data` to the equity slice, or move the
  rebalance onto a `Schedule.On(DateRules.EveryDay(), TimeRules.BeforeMarketClose(...))` event), not
  fire again 15 min later on the VIX slice. NOT in scope for the #268 grid decision; flagged here so
  Falk sees it. Filing suggestion: a separate "#26x once-per-day rebalance gate" ticket.

---

## Deliverable 2 — both fix directions, specced (NO application)

### Direction A — align LOCAL → CLOUD grid (local fills at day-open, T)

**Goal:** make local's daily bar reach `on_data` at midnight-ET so local submits at the open and fills
**same-day T**, moving local toward cloud's −9.05% / 291 orders / 113 symbols.

**The change (one knob):**
```python
# runtime/lean_entry.py :: initialize()  — NOT applied; spec only
self.settings.daily_precise_end_time = False   # daily bar EndTime = midnight, delivered at day OPEN
```
Files touched: `src/runtime/lean_entry.py` (1 line in `initialize`), then **rebuild dist**
(`build/cloud_package.py`) and **re-pin provenance** (config_hash is unaffected — this is a runtime
setting, not in `STRATEGY_CONFIG`/the phase closure — but `dist/` regenerates and the commit must be
re-pinned per the Dist-Provenance-Pin rule).

**Expected effect:** local's 60-equivalent open-bar entries appear; local's fill grid shifts one bar
earlier; local converges toward cloud's breadth/turnover (291/113) and its −9.05% trio. (It will not
be bit-identical — residual vendor coverage ~1.10× remains — but the entry grid would align.)

**Risk:** this **changes the champion's measured behavior** — every BT result on record (the +3.62% /
244 / −0.139 local trio, and every baseline derived from it) is invalidated and needs a **fresh parity
BT + full re-baseline**. It silently shifts every fill date for the entire history. High blast radius.

**Achievability:** **Likely yes, but UNCONFIRMED.** The setting is documented and engine-level, so
local `lean backtest` *should* honor `DailyPreciseEndTime=False` and deliver daily bars at midnight —
which is precisely what we observe cloud doing by default. The open risk: whether the *local* engine
build pinned in this repo respects the flag the same way cloud does (engine-version skew). **Confirm
by:** set the flag, run a 1-week local BT, and check the order-events `submitted` timestamps move from
21:00Z/20:00Z to 05:00Z/04:00Z. If they do, A is achievable. (Cheap to verify; do NOT skip.)

### Direction B — confirm LOCAL grid canonical (decide EOD-close T → fill open T+1)

**Goal:** declare LOCAL's grid (decide on the EOD close of T, fill at the open of T+1) the **faithful
BCT model** and treat CLOUD's day-open grid as the **optimistic artifact**. #262 then re-baselines to
LOCAL (−0.139 / +3.62% / 244), NOT the reverse.

**The argument it's canonical:** George scans BCT **after the close** (the day's OHLC/Ichimoku is only
complete at the close) and **buys the next session's open**. That is *exactly* local's grid: the daily
bar is delivered at market close (16:00 ET, complete bar), the decision is made on that complete bar,
and the MarketOnOpen order fills the **next** open (T+1). It has **no look-ahead**: it never acts on a
bar before that bar has closed.

**Why CLOUD is then the artifact:** cloud's midnight-ET delivery makes it submit at the open of T and
fill the **same** open T — i.e. it acts on day T's open using only data through T-1's close, **one bar
earlier on staler decision data**. For a "decide after close, buy next open" strategy that is the
optimistic/early grid: it captures T's open move that George (deciding only after T's close) could not
have traded until T+1. So under B, cloud's −9.05% is a mis-execution of the model, not ground truth.

**Operational consequences if Falk picks B:**
- **#262 re-baselines to the LOCAL trio** (−0.139 / +3.62% / 244 / 93). Cloud's −9.05% is recorded as
  "known-divergent execution venue", not the benchmark.
- **The cloud deploy** (`qc_v2_cloud` / `qc_pe_cloud`) must be made to **also fill next-open** to match
  the canonical grid. On QC cloud that means setting **`self.settings.daily_precise_end_time = True`**
  in the deployed `initialize()` — the mirror of Direction A, applied on the cloud side instead. This
  is the same one-line knob; per the docs `True` = market-close EndTime = local's grid. **Achievability
  on cloud: documented and expected to work** (it's a standard algorithm setting), but **confirm with a
  cloud BT** that cloud's `createdTime` moves from 04:00/05:00Z to 20:00/21:00Z. If for any reason cloud
  ignores the flag, the fallback is to accept cloud as a known-divergent venue (deploy paper/live only
  after a cloud-grid parity check).
- **No `src` strategy-logic change** — it's a setting + a re-baseline decision, lower blast radius than
  re-validating a shifted-grid champion.

### Side-by-side

| | Direction A (local→cloud) | Direction B (local canonical) |
|---|---|---|
| premise | cloud = ground truth (charter as-written) | LOCAL = George's faithful model; cloud = artifact |
| the change | `daily_precise_end_time=False` in local entry | `daily_precise_end_time=True` on the **cloud deploy**; keep local |
| #262 baseline | re-baseline to CLOUD (−9.05% / 291 / 113) | re-baseline to LOCAL (+3.62% / 244 / 93) |
| effect | local converges to cloud's early grid | cloud is forced onto local's next-open grid (or quarantined) |
| risk | invalidates EVERY recorded champion BT; full re-baseline | lower — a setting on the deploy + a baseline ruling |
| achievability | likely (confirm: local 1-wk BT, times → 04:00/05:00Z) | likely (confirm: cloud BT, times → 20:00/21:00Z) |

---

## Constraints honored
READ-ONLY investigation + this spec doc. No champion/dist/src/config change. No BT run. Every claim
evidenced (code line / LEAN-doc cite / order artifact). Where the LEAN default is not pinned by the
docs (the exact `DailyPreciseEndTime` default per engine), the most-likely mapping is stated from the
**observed** submission timestamps and the confirm step is given. mypy: this doc carries no code.
