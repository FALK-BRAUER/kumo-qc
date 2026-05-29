# V9 Sector Rotation (GH #136) — Window Results

**Concept:** Only trade names in top-3 sectors by 3-month relative strength.
Uses 11 SPDR sector ETFs (XLK, XLI, XLF, XLY, XLV, XLP, XLC, XLE, XLU, XLB, XLRE).
Computes 63-day returns, ranks, filters candidates to top-3 sectors.
**Baseline:** e40c FY2025 Sharpe = 0.778 / flat W1 Sharpe = 0.984

## Rolling 6-Month Windows (2025)

| Window | Period | Sharpe | Orders | DD | Win% | Return | Status |
|--------|--------|--------|--------|-----|------|--------|--------|
| W1 (Jan-Jun) | **1.610** | 65 | 9.6% | 43% | 34.957% | ✅ |
| W2 (Feb-Jul) | -0.125 | 78 | 9.7% | 32% | 5.482% | ❌ |
| W3 (Mar-Aug) | -0.244 | 72 | 6.2% | 35% | 3.852% | ❌ |
| W4 (Apr-Sep) | **0.966** | 81 | 6.2% | 36% | 22.500% | ✅ |
| W5 (May-Oct) | **1.233** | 95 | 6.2% | 35% | 29.587% | ✅ |
| W6 (Jun-Nov) | **1.782** | 92 | 7.5% | 33% | 44.929% | ✅ |

**Positive windows:** 4/6 (W1, W4, W5, W6)
**Threshold:** 4+/6 required → **MET** ✅

## Full FY2025
| Metric | Value |
|--------|-------|
| Sharpe | **0.573** |
| Orders | 149 |
| Drawdown | 9.6% |
| Win Rate | 40% |
| Return | 18.174% |

## Analysis
- **W1 exceptional (1.610):** Strong sector momentum in H1 2025. Top sectors (Tech, Industrials, Financials) delivered outsized returns.
- **W2-W3 near-zero/negative:** Transitional periods where sector rotation caused missed entries in recovering sectors or chased lagging momentum. Minor negative Sharpe (-0.125, -0.244) but not catastrophic.
- **W4-W6 strong recovery:** Sector momentum persisted. W6 at 1.782 is the best window result.
- **FY2025 0.573:** Below e40c 0.778 baseline. The sector filter adds specificity but also misses some cross-sector opportunities that e40c captures.
- **Order count reduction:** 149 orders FY2025 vs ~196 for e40d, showing sector filter reduces entry count by ~24%.
- **Lower drawdown:** 9.6% vs e40c's ~11.8%, suggesting sector rotation improves risk-adjusted behavior despite lower Sharpe.

## Verdict
**MARGINAL / HOLD for further tuning.** 
- 4/6 windows positive meets threshold
- FY2025 Sharpe 0.573 < e40c 0.778 (does not beat baseline)
- W1 Sharpe 1.610 > e40c flat W1 0.984 (strong single window)
- Suggestion: Test with different RS lookback (1-month vs 3-month) or top-2 vs top-3 sectors
