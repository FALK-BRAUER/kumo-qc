# #173 First-Divergence-Day Root-Cause — champion_asis Cloud vs Local (full-FY2025)

**Status:** ROOT-CAUSED. Verdict = **hypothesis (a) selection-breadth**, specifically the
**WARMUP-PERIOD coarse-feed breadth**. Hypothesis (b) data-normalization is **RULED OUT**
(RAW prices match cloud↔local).

## Artifacts (every number below traces to one of these)

| Side | Artifact |
|---|---|
| CLOUD | BT `8cd94678f037055e1bf4263ee4c9315f`, project `arch2_champion_v2` PID `32319236`. 324 orders pulled via `/backtests/orders/read` (throwaway fetch; see report). 118 unique symbols. |
| LOCAL | `/Users/falk/projects/kumo-qc-baseline/algorithm/v2_champion_asis/backtests/2026-05-31_20-46-41/` — `1518836179-order-events.json` (72 filled events / 75 orders, 37 symbols) + `log.txt` (ACTIVE_SET / TRACKED_CANDIDATES / REBALANCE / ENTRY lines) + `data-monitor-report` (0 failed data requests). |
| Coarse feed | `data/equity/usa/fundamental/coarse/2025MMDD.csv` + warmup-era `2023*/2024*.csv`. |
| Daily zips | `data/equity/usa/daily/<t>.zip` (RAW OHLCV ×10000). |

Headline metrics (given): CLOUD −0.787 Sharpe / −11.8% / 324 orders / 118 symbols;
LOCAL −0.616 Sharpe / +3.9% / 75 orders / 37 symbols.

---

## 1. First-divergence day + symbol(s)

**First divergence = the FIRST trading day, 2025-01-02.**

- **CLOUD** trades **10 symbols on 2025-01-02** (the first bar): AXP, C, DRI, ET, HPE, JPM,
  MRVL, T, UAL, V (market-on-open). [/orders, time=2025-01-02]
- **LOCAL** trades **NOTHING on 2025-01-02**. Its first (and only Jan) entry is **SPY on
  2025-01-03**. [order-events; log `ENTRY|2025-01-03|SPY`]

No symbol overlap on the divergence day — cloud's 10 day-1 names are not traded locally at all
on 01-02/01-03.

---

## 2. Universe → signal → trade diff at the divergence day

### Universe (ACTIVE_SET / TRACKED_CANDIDATES from the local log)

| Date | LOCAL ACTIVE_SET count | CLOUD (order proxy) |
|---|---|---|
| every warmup day 2023-06-21 → 2024-12-31 | **count=0** (all 636 warmup lines) | populated (traded day 1) |
| 2025-01-02 (first live day) | **no ACTIVE_SET / TRACKED line emitted → 0 names** | 10 names traded |
| 2025-01-03 | **count=733** (universe suddenly populates) | — |
| month-end Jan | ~860 | — |

The local universe is **empty for the entire 18-month warmup and on the first live day**, then
jumps to 733 on day 2. The cloud universe was populated from day 1 (and, by inference from the
indicator-readiness behaviour below, throughout warmup).

### Signal (BCT 8-condition score, `score_symbol_native`, min_score=7)

`score_symbol_native` (shared_oracle_helpers.py:148) returns **None until every maintained
indicator is ready** — `d_ichi, w_ichi, sma200, adx, roc13` all `is_ready` AND `w_close.count≥27`
AND `adx_window.count≥4`. The maintained daily/weekly Ichimoku + ADX + SMA200 + ROC are
auto-warmed by QC **only while a symbol is SUBSCRIBED**. A symbol is subscribed only when the
coarse universe selection returns it.

- **LOCAL:** zero universe names subscribed during the 2023-06→2024-12 warmup → their indicators
  were **never warmed**. When 733 names finally appear on 2025-01-03 their indicators are
  freshly-registered (only the WEEKLY ichimoku is seeded from `history()` via `_seed_weekly`;
  daily Ichimoku/SMA200/ADX/ROC accumulate live from scratch) → `is_ready` is False → score=None
  → nothing qualifies. Only **SPY** (hard-subscribed at `Initialize` via `add_equity`, warmed the
  whole 18 months) scores ≥7 and trades.
- **CLOUD:** universe populated throughout warmup → indicators warm by 2025-01-02 → 10 names
  score ≥7 on day 1.

### Trade (sizing + fill)

Sizing = flat 10% of equity per name, cash-heat-capped (FlatPctHeatcap), entries via
`market_on_open_order`. ~10 names × 10% ≈ cash exhausted → matches cloud's 10–15 day-1 entries.
Local had nothing to size on 01-02 and only SPY on 01-03.

### The "local wakes up in October" tell (monthly buy counts)

| Month | CLOUD buys | LOCAL buys |
|---|---|---|
| 2025-01 | 34 | 2 (SPY only) |
| 02 | 12 | 0 |
| 03 | 24 | 0 |
| 05 | 27 | 1 (SPY) |
| 08 | 15 | 1 (SPY) |
| 10 | 18 | **20** |
| 11 | 18 | 8 |
| 12 | 8 | 8 |

Local trades almost nothing Jan–Sep, then bursts in **October** — ~9–10 months after warmup
ended, i.e. exactly when the from-scratch daily indicators on the broad universe (subscribed
2025-01-03) finally accumulate enough LIVE bars to become `is_ready` and score ≥7. This is the
fingerprint of an **unwarmed-indicator** divergence, not a data-vendor one.

---

## 3. Root-cause verdict — (a) selection-breadth, WARMUP coarse feed

### (a) SELECTION — CONFIRMED, dominant cause

The local **conform-coarse feed is sparse/wrong-format/absent during the warmup window**:

| Coarse file | rows | format |
|---|---|---|
| `20230621.csv` … `20241231.csv` (warmup era) | **~201** (some dates **1 row**, some **missing**: 20240601, 20241201 absent) | 5-col **with header** `Symbol,Price,Volume,DollarVolume,HasFundamentalData` |
| `20250102.csv` onward (live) | **10,622** | 8-col **headerless** QC-native `securityID,ticker,close,vol,dollarVol,hasFund,priceFactor,…` |

The warmup-era files are a **hand-built top-~200 synthetic universe in a non-QC format**, while
the live-period files are the full QC-native coarse. Result: the local engine had an **empty
coarse universe for the entire warmup** (ACTIVE_SET count=0 on all 636 warmup days) → no
subscriptions → no indicator warmup → no day-1 qualifiers. Cloud uses QC's native coarse for the
full warmup → warm indicators → day-1 qualifiers.

### (b) DATA-NORMALIZATION — RULED OUT

For the day-1 divergent names the RAW price series is IDENTICAL cloud↔local:

| Sym | Local coarse close (`20250102.csv` col3) | Local daily-zip RAW close | Local daily-zip RAW **open** | Cloud fill price (market-on-open) |
|---|---|---|---|---|
| DRI | 186.47 | 186.47 | **188.47** | **188.47** (= open) |
| AXP | 298.56 | 298.56 | **300.00** | **300.00** (= open) |
| ET | 19.74 | 19.74 | 19.56 | 19.50 |
| HPE | 21.48 | 21.48 | 21.44 | 21.51 |

Cloud fills at the **same-day OPEN** (market-on-open); local coarse carries the **same-day
close** — both RAW, same underlying series. The cloud-vs-local price difference is a
fill-TIMING artifact (open vs close of the same RAW bar), NOT a vendor/normalization delta.
Engine sets `DataNormalizationMode.RAW`; confirmed RAW both sides.

### Scale of (a) — the key numbers

- **95 of 118 cloud symbols (81%) are never traded locally.** Overlap = 23 symbols; cloud-only =
  95; local-only = 14. [/orders vs order-events]
- **Local universe = 0 names for 18 months of warmup + day 1**, vs cloud populated throughout.
- All 10 day-1 cloud symbols ARE present in the local *live-period* conform-coarse (`20250102.csv`)
  and ALL pass the floors (price≥10, DV≥100M) — DRI DV=132M, ET=231M, HPE=197M, etc. So the
  live-period coarse is fine; the defect is **isolated to the warmup window**.
- 0 failed local data requests; DRI/AXP/ET/HPE/MRVL daily zips each carry 916 bars before
  2025-01-02 → local HAD the price data to warm indicators; it simply never subscribed the names
  during warmup because the warmup coarse feed was empty.

---

## 4. Recommended fix direction (DIAGNOSIS ONLY — do not implement)

The break is **(a) warmup-period coarse-feed breadth**, so the local harness does NOT emulate
cloud during warmup. Per the Cloud/Local Parity charter (local = harness that emulates cloud):

1. **Regenerate the local conform-coarse for the FULL warmup window (2023-06 → 2024-12) to QC-native
   breadth + format.** The warmup files must be the same ~10k-name headerless 8-col QC-native
   coarse as the 2025 files, so the warmup universe matches cloud and the same names get
   subscribed + indicator-warmed. This is the single highest-leverage fix — it restores day-1
   parity directly.
2. If full QC-native warmup coarse is impractical locally, **shorten/seed differently:** explicitly
   `history()`-seed the DAILY Ichimoku/SMA200/ADX/ROC (not just the weekly) for every name the
   day it enters the universe, so a name can qualify the day it is first subscribed rather than
   ~10 months later. This removes the dependency on warmup-window subscription. (Note: today only
   `_seed_weekly` seeds — the daily suite is left to accumulate live, which is the mechanical
   amplifier of the empty-warmup defect.)
3. **Accept-and-document fallback:** if neither is feasible, declare cloud the ground truth and
   local an explicit narrow approximation that is NOT valid for the first ~10 months of any
   window. Under this fallback the local +3.9% / −0.616 number is an artifact of an empty universe,
   NOT a real strategy result — it must not be used as a parity baseline.

**Do not** add an `if cloud` branch. The fix is to make the local warmup coarse feed match cloud,
or to seed the full indicator suite per-subscription — both keep a single code path.

---

## 5. Unobtainable / flagged

- Cloud per-day ACTIVE_SET via `/chart/read` was NOT used (charter flags it flaky); the cloud
  **order list** was used as the trade/selection proxy throughout, as instructed. All cloud
  numbers come from `/backtests/orders/read` (324 orders, verified paginated 100×3+24).
- Cloud per-day universe COUNT during warmup is not directly observable from the order list; it is
  **inferred** (cloud traded 10 names on day 1, which requires warm indicators, which requires
  warmup subscription). This inference is consistent with all observed evidence and the engine
  code path; it is labelled an inference, not a measured count.
