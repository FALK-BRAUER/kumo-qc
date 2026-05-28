# 6-Week Run-Up Summary: E40d Champion Lock-In

**Date:** 2026-05-28
**Status:** Experiment queue exhausted. E40d champion confirmed at 1.442 Sharpe.

## What We Were Trying to Achieve

Improve on the E40d champion (1.442 Sharpe, +42.4% FY2025) by testing additional entry/exit gates, regime filters, and position sizing variations. The E40d base is: polygon-326 universe, BCT ≥7/8 entry, 10% fixed sizing, 10 max positions, Kijun stop, SPY>50MA + VIX<25 regime gate.

## Key Results (Week-by-Week)

### Week 1-2: E47 Sector Regime Gate (GH #114)
- **Hypothesis:** Block entries when sector ETF weekly price is below cloud
- **Result:** 💀 CATASTROPHIC — 0.583 Sharpe (-0.685 delta)
- **Key Finding:** BCT stock selection is already sector-agnostic and superior. Sector gates create false negatives that dominate any false positive reduction.
- **Blocked entries:** 59 (42 in XLV Healthcare)

### Week 3: E40d-v3 VIX<<30 (GH #104)
- **Hypothesis:** Looser VIX threshold (30 vs 25) allows more entries during elevated vol
- **Result:** ❌ REJECTED — 1.379 Sharpe (-0.063 delta)
- **Key Finding:** VIX<<25 is the sweet spot. Looser threshold adds 38 regime-block days and degrades Sharpe.

### Week 4: E46 Weekly BCT Pre-Filter (GH #113)
- **Hypothesis:** Require weekly BCT score ≥ threshold before daily entry
- **Result:** ❌ REJECTED — Thresholds 1-3 identical to baseline. Threshold 4 degrades Sharpe 1.268 → 1.152.
- **Key Finding:** Weekly Ichimoku is redundant with daily BCT pipeline. The daily score ≥7 already implicitly requires strong weekly setups.

### Week 5: E40d-v2 VIX<<20 (GH #106)
- **Hypothesis:** Stricter VIX threshold (20 vs 25) filters more noise
- **Result:** ❌ REJECTED — 0.687 Sharpe (significant degradation)
- **Key Finding:** VIX<<25 is optimal. Too strict halves return to +22.4%.

### Week 6: E89 Unlimited Slots + Risk Sizing (GH #118)
- **Hypothesis:** Replace fixed 10 slots with $200 risk per position, unlimited positions
- **Result:** 💀 CATASTROPHIC — 0.222 Sharpe (-1.220 delta)
- **Key Finding:** 44 concurrent positions = over-diversification that dilutes returns. Fixed 10 slots @ 10% is optimal.

## Champion Status

| Metric | E40d Value |
|--------|-----------|
| FY2025 Sharpe | **1.442** |
| FY2025 Return | +42.4% |
| Orders | ~230 |
| Win Rate | 44% |
| Max Drawdown | 10.7% |
| Regime Gate | SPY>50MA + VIX<25 |
| Universe | polygon-326 |
| Sizing | 10% fixed, 10 max positions |
| Exit | Kijun stop + weekly Kijun stop |

## Architectural Findings Confirmed

1. **BCT checklist is maximal** — No additional entry gates improve performance (E8, E38, E49, E53, E46, E87 all rejected)
2. **Regime gates are the only positive axis** — But only at correct thresholds (VIX<<25 is sweet spot)
3. **Sector-level filtering is catastrophic** — E47 proved sector gates destroy alpha
4. **Fixed 10% sizing is optimal** — Every position sizing variant (E26, E42, E89) hurts performance
5. **Weekly Ichimoku is redundant** — Daily BCT ≥7 already captures weekly strength

## What Changed in the Codebase

- `algorithm/performance_bct/sector_mapping.json` — 325 tickers mapped to GICS sectors
- `EXPERIMENT-LOG.md` — 86 experiments documented, queue now empty
- `bt-results.csv` — All results tagged with experiment IDs
- `CLAUDE.md` — Worker regime, credentials, commit policy documented

## What Didn't Change

E40d champion code remains unchanged. No accepted experiment since E40d (cloud-e40d branch, 1.442 Sharpe).

## Next Steps

Experiment queue is empty. All identified axes tested and rejected. Options:

1. **Deploy E40d to paper live** — gate.py unlock → DUK434934
2. **Research new axes** — What haven't we tested? (e.g., alternative data, ML overlay, options overlay)
3. **Accept E40d as final champion** — Lock the strategy, focus on execution quality

## Risk Notes

- 34 commits on `cloud-e40d` branch unpushed to origin
- Uncommitted changes in `algorithm/performance_bct/main.py` (ATR stop, pyramid add, earnings path fixes — accumulated experiment code)
- GitHub issues #104, #113, #114, #118 still open
- QC project 32034565 (performance_bct) has missing data/permissions issues — local LEAN is the reliable target

---

*Summary prepared for Falk. Direct, technical. No buzzwords.*
