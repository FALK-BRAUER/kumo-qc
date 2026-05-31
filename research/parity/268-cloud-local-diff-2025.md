# #268 Root-Cause Localization — Cloud ORDERS vs Local Indicators (FY2025)

**Channel:** RELIABLE only — cloud `/backtests/orders/read` (291 orders) + the local indicator
series already captured (`local-indicators-243.json`, 497 pts each / 250 distinct dates).
The flaky `/chart/read` capture (`cloud-indicators-243.json`) had **NOT landed** at report time
(capture process still grinding) — so the direct cloud-vs-local MA200/score series diff is
**deferred**; everything below is resolved via orders + local series alone.

- **Cloud BT:** `8ddbe2b449df87edba5d3fd50b48bea1`, project `arch2_champion_v2`
  (`v2-243-chartemit-fullFY`). Trio **−0.683 / −9.05% / 291** (inert-emit confirmed).
- **Local trio:** **−0.139 / +3.62% / 244** (`local-indicators-243.json`).
- **Gap to localize:** 291 cloud vs 244 local orders (**47-order gap**);
  cloud 113 distinct traded symbols vs local 93 (**20-symbol gap**).

Diagnostic only. RAW. Champion/dist/src untouched. Every number below is from a real
artifact/API call — see `scripts/diff_268_orders_indicators.py` and
`research/parity/artifacts/268-diff-orders-vs-local-indicators.json`.

---

## Order / symbol-set decomposition (cloud orders vs local traded set)

| metric | value |
|---|---|
| cloud orders | 291 (153 buys / 138 sells) |
| cloud distinct traded symbols | 113 |
| local traded symbols | 93 |
| overlap (traded by both) | 75 |
| **cloud-only symbols** (cloud bought, local never traded) | **38** |
| local-only symbols (local traded, cloud never) | 18 |

The 38 cloud-only symbols include all 6 #265 probes:
`ALL, AMZN, BECN, BRK.B, CAH, CDNS, CHWY, CMA, CME, COST, CRWD, CTVA, DRI, EBAY, ED, EXC, ISRG,
ITCI, IVV, JCI, KGC, KRE, MO, NOC, RBA, SHY, SLV, SMH, SNOW, SPGI, TMUS, TWLO, USO, VOO, VRSK,
XEL, XLK, XYZ`.

---

## (d) REGIME-TIMING — **NOT material. Effectively zero share of the residual.**

- Local regime-BLOCKED days (Regime/spy_close < Regime/spy_ma200): **42 days**, clustered in a
  single window **2025-03-10 → 2025-05-09** (matches #265's ~42-day Mar–May cluster exactly).
- Cloud BUY orders that land on a local-blocked day: **0 of 153** (0.0%).

Cloud does **not** enter on a single day that local's SPY-MA200 regime gate blocks. Whatever
small MA200 value gap may exist cloud-vs-local (only the landed cloud chart can quantify the
absolute gap), it does **not** translate into cloud entries inside local's blocked window.
**(d) is not the residual driver.** The clean direct test (cloud spy_ma200 vs local spy_ma200
per date) still needs the cloud chart, but the *behavioral* test — does cloud trade when local's
regime is shut — is answered NO via orders alone.

---

## (c) SCORING / conformed-vs-native bar-set — **NOT the mechanism it was framed as.**

For each probe, cloud's BUY date and local's Score on that exact date:

| probe | cloud buy date | local Score (that date) | local qualified (≥7)? | regime blocked? | local n_qualifying (that date) |
|---|---|---|---|---|---|
| DRI | 2025-01-02 | **−1.0** (sentinel: not active) | no | no | 10 |
| DRI | 2025-03-25 | **−1.0** (sentinel) | no | no | 0 |
| CME | 2025-08-04 | **7.0** | **yes** | no | 4 |
| AMZN | 2025-01-03 | **7.0** | **yes** | no | 0 |
| COST | 2025-02-12 | **8.0** | **yes** | no | 0 |
| CRWD | 2025-02-13 | **8.0** | **yes** | no | 0 |
| KGC | 2025-03-25 | **8.0** | **yes** | no | 0 |

**Key result:** on the cloud-buy date, local **scores 5 of the 6 probes ≥ 7** (CME 7, AMZN 7,
COST 8, CRWD 8, KGC 8) — i.e. local's own per-name score QUALIFIES the very names it never
traded. Only DRI is below threshold, and as a `−1` *sentinel* (DRI simply wasn't in local's
active universe on those two dates), not a low computed score.

So the hypothesis "local scores the cloud-traded names BELOW threshold because the conformed
daily bar-set yields different Ichimoku/ADX/SMA" is **falsified for 5 of 6 probes**. The
indicator VALUES feeding the score are close enough that local clears the threshold. **(c) as a
score-magnitude divergence is not the residual driver.**

---

## What the residual ACTUALLY is — a BREADTH / qualifying-gate divergence (internal contradiction)

The diff surfaced a contradiction **inside the local series itself**, which is the real story:

- Across all 153 cloud buys, local **`n_qualifying == 0` on the buy date for 75 of them (49%)**;
  of the 42 distinct cloud-buy dates, **27 (64%) have local n_qualifying == 0**.
  Yet on several of those same dates local's per-name Score for the bought name is **8**
  (COST 2025-02-12, CRWD 2025-02-13, KGC 2025-03-25). A name scores 8 but the aggregate
  qualifying-count is 0 — same timestamp, same emit (verified: both series sampled at the
  identical 21:00/21:15Z points). The active universe is full those days (active_set 767–959)
  and the regime is OPEN.

- Local `n_qualifying` is near-zero almost all year and spikes to 100–134 **only in Mar–May** —
  i.e. local qualifies the MOST names *precisely during its own regime-blocked window* and
  almost nothing the rest of the year:

  | month | days n_qualifying>0 / total | max n_qualifying |
  |---|---|---|
  | 2025-01 | 3/20 | 10 |
  | 2025-02 | 5/19 | 2 |
  | 2025-03 | 16/21 | 105 |
  | 2025-04 | 21/21 | 114 |
  | 2025-05 | 8/21 | 134 |
  | 2025-06 | 2/20 | 1 |
  | 2025-07 | 2/22 | 2 |
  | 2025-08 | 3/21 | 4 |
  | 2025-09 | 1/21 | 1 |
  | 2025-10 | 2/23 | 5 |
  | 2025-11 | 4/19 | 1 |
  | 2025-12 | 3/22 | 1 |

Cloud, by contrast, buys steadily across all 12 months (113 symbols, 153 buys). The 47-order /
20-symbol gap is therefore dominated by **local qualifying far fewer names per day than cloud**,
NOT by local scoring cloud's names below threshold and NOT by a regime-timing offset.

The per-name Score and the aggregate `n_qualifying` counter disagree on the same date → local's
qualifying gate applies an **additional filter between scoring and the tradeable count** that
collapses local's breadth outside Mar–May (and inverts it inside Mar–May). This is the lever
the #268 fix must target.

---

## Which dominates + share of the gap

| candidate | verdict | share of the 47-order / 20-symbol gap |
|---|---|---|
| **(d) SPY-MA200 regime-timing** | **NOT material** | **~0%** — 0/153 cloud buys on local-blocked days |
| **(c) score-magnitude / bar-set** | **NOT the framed mechanism** | small/none — local scores 5/6 probes ≥7 on cloud's buy date |
| **breadth / qualifying-gate** (newly localized) | **DOMINANT** | drives the bulk — local n_qualifying==0 on 49% of cloud buys / 64% of cloud-buy dates, while per-name scores clear threshold |

**Dominant residual = the qualifying/selection gate, not regime timing and not the daily
bar-set scoring.** Local computes high per-name scores but a downstream gate zeroes the
qualifying count on ~half of cloud's entry dates; the only true threshold miss among probes is
DRI, and that is a `−1` universe-inactive sentinel, not a computed-score gap.

---

## What still needs the cloud chart

Resolved via **orders alone** (no chart needed):
- (d) behavioral test — cloud does not enter on local-blocked days (0/153).
- (c) score-magnitude test — local scores 5/6 probes ≥7 on cloud's buy date.
- The breadth localization — local n_qualifying==0 on 49% of cloud buys.

Still needs the landed **`cloud-indicators-243.json`** (deferred, capture not yet landed):
- The **absolute SPY-MA200 value gap** cloud-vs-local per date (the clean (d) magnitude test —
  behaviorally already shown immaterial, but the value gap quantifies vendor-bar residual).
- **Cloud's own n_qualifying** per day vs local's — to confirm cloud's qualifying gate stays
  open year-round while local's collapses (the direct breadth diff). The script
  `diff_268_orders_indicators.py` already auto-ingests `cloud-indicators-243.json` and emits the
  MA200 gap + block-day-delta + breadth comparison if/when it lands — rerun then, no code change.
- Cloud's per-name Score on its own buy dates — to confirm cloud scores the 38 cloud-only names
  the same way local does (which would pin the divergence entirely on the gate, not the score).

---

## Points the #268 FIX at

The qualifying/selection gate — specifically the step **between per-name scoring and the
n_qualifying tradeable count**. Local's qualifying count collapses to 0 on ~half of cloud's entry
dates and inverts (spikes only Mar–May) despite full active universe and open regime and despite
per-name scores ≥7. That gate's dependency (it currently behaves opposite to the regime/score
inputs) is the lever, NOT the SPY warmup/MA200 source (d immaterial) and NOT the conformed-vs-
native daily bar-set scoring (c falsified for 5/6 probes). The conformed bar-set may still cause
small score wobble, but it is not what loses the 47 orders / 20 symbols.

## Artifacts
- `research/parity/artifacts/cloud-orders-243.json` — 291 cloud orders (this BT, via `/orders/read`)
- `research/parity/artifacts/268-diff-orders-vs-local-indicators.json` — machine-readable diff
- `scripts/diff_268_orders_indicators.py` — the diff (mypy --strict clean; auto-ingests cloud chart if landed)
