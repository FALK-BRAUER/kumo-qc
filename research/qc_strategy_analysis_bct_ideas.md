# QC Community Strategy Analysis — BCT Improvement Ideas

## Executive Summary

**Analyzed:** All 4 requested strategies
- ✅ TheOmniscientParadox (QC #1, failed OOS 51.5% DD)
- ✅ IRPrecisionFalcon (shows alpha FY2024/25)
- ✅ DualMomentumTechStocks (from HQ chat history)
- ✅ ConditionalSectorRotation (from HQ chat history)

**Top 7 BCT-Compatible Ideas Identified — UPDATED RANKING:**

---

## 1. TheOmniscientParadox (QC Rank #1)

### Methodology Summary
- **Type:** Single-asset daily momentum rotation
- **Universe:** Leveraged sector/index ETFs (SPXL, TQQQ, SOXL, etc.)
- **Signal:** Composite momentum from 3 ROC horizons (short/med/intermediate), volatility-scaled
- **Filter:** 50-day trend filter (price > 50SMA gets full credit)
- **Risk Control:** RSI penalty for extreme overbought/oversold
- **Position:** Concentrated (1 ETF at a time), rotation threshold-based
- **Cash:** Shifts to cash-like when momentum deteriorates

### Performance
- Sharpe 1Y: 3.96
- DD 5Y: 41% (FAILED OOS — too high for BCT)
- Return 3M: +160%

### BCT-Compatible Ideas

#### Idea 1: **Volatility-Scaled Momentum Score (E19)**
- **What:** Scale momentum signal by 1/realized_vol (prefer smoother trends)
- **BCT Fit:** Add to condition #7 (ADX) or as separate gate
- **Expected Impact:** Medium — reduces chop entries
- **Complexity:** Low — use 20-day realized vol
- **Alignment:** High — fits BCT's smooth-trend philosophy

#### Idea 2: **Multi-Horizon Momentum Confirmation (E20)**
- **What:** Require 10d, 20d, 50d momentum aligned (not just price > cloud)
- **BCT Fit:** Add to weekly confirmation (condition #2: Tenkan > Kijun)
- **Expected Impact:** Medium-High — stronger trend validation
- **Complexity:** Low — already have daily/weekly, just extend
- **Alignment:** High — strengthens existing BCT logic

#### Idea 3: **RSI Extreme Avoidance (E21)**
- **What:** Skip entries when RSI > 75 (overbought) or < 25 (oversold)
- **BCT Fit:** New condition #9 or soft gate
- **Expected Impact:** Low-Medium — reduces whip-saw entries
- **Complexity:** Low — single indicator
- **Alignment:** Medium — BCT is trend-following, RSI is mean-reversion

### Why It FAILED OOS
- 51.5% max drawdown — volatility-scaling insufficient for leveraged ETFs
- Concentrated single-asset risk — BCT's diversification (10 positions) is superior
- No trend regime detection — BCT's weekly cloud context is better

---

## 2. IRPrecisionFalcon / High-Conviction Mega-Cap Rotation vs QQQ

### Methodology Summary
- **Type:** ML-based benchmark-relative rotation
- **Universe:** MAG8 (AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA, AMD) + QQQ
- **Signal:** RandomForest on 2 features (10d return, 10d active return vs QQQ)
- **Label:** Stock beats QQQ over next 5 days
- **Gate:** Probability > 0.70 → 98% in predicted winner
- **Fallback:** Hold QQQ when signal uncertain (suppressing tracking error)
- **Retrain:** Monthly on 500-day history

### Performance
- Sharpe 1Y: 2.14 (QC data)
- DD 5Y: 43.6%
- Shows genuine alpha in FY2024/2025 per Falk

### BCT-Compatible Ideas

#### Idea 4: **Benchmark-Relative Active Return Filter (E22)** ⭐ TOP PICK
- **What:** Only enter if stock's 10d active return (vs SPY/QQQ) > threshold
- **BCT Fit:** Add to fine filter before BCT scoring
- **Expected Impact:** High — ensures entering outperformers, not just absolute trends
- **Complexity:** Medium — need benchmark data
- **Alignment:** High — complements Ichimoku trend with relative strength

#### Idea 5: **ML Signal Overlay (E23)**
- **What:** Train lightweight model (RF/XGBoost) on BCT features to predict 5d forward return
- **BCT Fit:** Use as entry gate or sizing modifier
- **Expected Impact:** Medium — adds non-linear feature interactions
- **Complexity:** High — requires training infrastructure, feature engineering
- **Alignment:** Medium — BCT is rules-based, ML adds opacity

#### Idea 6: **High-Confidence Probability Gate (E24)**
- **What:** Only enter when signal confidence > 70% (like IRPF's 0.70 prob gate)
- **BCT Fit:** Use ADX > 25 or composite score = 8/8 as "high confidence"
- **Expected Impact:** Medium — already partially implemented via score >= 7
- **Complexity:** Low — tighten to score = 8/8 only
- **Alignment:** High — similar to existing score threshold

#### Idea 7: **Benchmark Fallback (E25)**
- **What:** When no BCT signals score >= 7, hold SPY/QQQ instead of cash
- **BCT Fit:** Alternative to cash during signal droughts
- **Expected Impact:** Medium — reduces tracking error vs buy-and-hold
- **Complexity:** Low — simple else-branch
- **Alignment:** Medium — BCT is active, but beta exposure beats cash drag

---

## 3. DualMomentumTechStocks (from HQ chat history)

### Methodology Summary
- **Type:** Long-only cross-sectional momentum rotation on large liquid US tech equities
- **Universe:** Large liquid US tech equities
- **Signal:** Top 10 by 90-day momentum (positive momentum only)
- **Rebalance:** Monthly
- **Sizing:** Inverse 20-day realized volatility sizing (higher vol = smaller position)
- **Risk Control:** Per-position stop loss at 2% of portfolio value
- **Cash Management:** GLD as cash substitute when no qualifying names

### BCT-Compatible Ideas

#### Idea 8: **Inverse Volatility Sizing (E26)** ⭐ HIGH PRIORITY
- **What:** Scale position size by 1/σ (20-day realized vol)
- **BCT Fit:** Replace flat 10% sizing with vol-adjusted sizing
- **Expected Impact:** High — reduces risk concentration in volatile names
- **Complexity:** Low — 20-day vol already calculable
- **Alignment:** High — BCT's phase 3 cloud stop is similar logic for exits

#### Idea 9: **Monthly Momentum Ranking Pre-Filter (E27)**
- **What:** Filter universe to top N by 90d momentum before BCT scoring
- **BCT Fit:** Replace coarse liquidity filter with momentum-ranked universe
- **Expected Impact:** Medium-High — ensures all candidates have baseline trend
- **Complexity:** Low — momentum calc trivial
- **Alignment:** Medium — BCT uses Ichimoku, not pure momentum

#### Idea 10: **GLD/SPY Cash Substitute (E28)**
- **What:** When no BCT signals >= 7, hold GLD or SPY instead of cash
- **BCT Fit:** Alternative to pure cash during signal droughts
- **Expected Impact:** Medium — reduces cash drag, maintains exposure
- **Complexity:** Low — single line in rebalance logic
- **Alignment:** Medium — BCT is active but gold/SPY better than cash

#### Idea 11: **Per-Position Stop Loss (E29)** — NOT RECOMMENDED
- **What:** 2% portfolio value stop per position
- **BCT Fit:** Conflicts with existing Kijun-based stop
- **Expected Impact:** Low — BCT's cloud/Kijun stop is more sophisticated
- **Alignment:** Low — Ichimoku already provides dynamic stops

---

## 4. ConditionalSectorRotation (from HQ chat history)

### Methodology Summary
- **Type:** Leveraged ETF rotation system
- **Universe:** SPY/QQQ/TQQQ/UVXY/TECL/SPXL/SQQQ/TECS/BSV
- **Regime Gate:** SPY SMA200 as bull/bear filter
- **Signal:** RSI thresholds for rotation
  - RSI > 81 on QQQ → flee to UVXY (volatility hedge)
  - RSI < 30 → buy SPXL/TECL (leveraged long)
- **Position:** 100% concentration, daily rebalance
- **Execution:** SetHoldings with liquidateExistingHoldings=True

### BCT-Compatible Ideas

#### Idea 12: **RSI Overbought Portfolio Gate (E30)** — LOW PRIORITY
- **What:** When market RSI > 80, exit all positions to cash/hedge
- **BCT Fit:** Global risk-off signal
- **Expected Impact:** Low-Medium — contradicts trend-following
- **Complexity:** Low
- **Alignment:** Low — BCT is trend-following, RSI extremes fade trends
- **Verdict:** Skip — conflicts with BCT philosophy

#### Idea 13: **SPY SMA200 Regime Filter (E31)** — NOT NEEDED
- **What:** Only trade when SPY > 200-day SMA
- **BCT Fit:** Bull/bear regime detection
- **Expected Impact:** Low — BCT already has weekly cloud context
- **Alignment:** Medium — cloud provides same regime info
- **Verdict:** Skip — BCT's weekly Span A/B already handles this

#### Idea 14: **Leveraged ETF Universe (E32)** — ALREADY TESTED
- **What:** Trade TQQQ/SPXL instead of unlevered
- **BCT Fit:** Amplify returns in trending markets
- **Expected Impact:** High risk/reward — already tested in #67-#69
- **Alignment:** Low — 21 experiments show equity-only is optimal
- **Verdict:** Skip — EXP-ETF already tested, equity-only wins

---

## UPDATED Shortlist: Top 7 Ideas from All 4 Strategies

| Rank | Idea | Source | Impact | Complexity | Alignment | BCT Fit | Status |
|------|------|--------|--------|------------|-----------|---------|--------|
| 1 | **Inverse Volatility Sizing (E26)** | DualMomentumTechStocks | **HIGH** | Low | **HIGH** | Position sizing | ⭐ RECOMMENDED |
| 2 | **Benchmark-Relative Active Return Filter (E22)** | IRPrecisionFalcon | **HIGH** | Medium | **HIGH** | Pre-BCT gate | ⭐ RECOMMENDED |
| 3 | **Monthly Momentum Ranking (E27)** | DualMomentumTechStocks | Med-High | Low | Medium | Universe filter | ✅ VIABLE |
| 4 | **Multi-Horizon Momentum Confirmation (E20)** | TheOmniscientParadox | Med-High | Low | **HIGH** | Weekly condition | ✅ VIABLE |
| 5 | **GLD/SPY Cash Substitute (E28)** | DualMomentumTechStocks | Medium | Low | Medium | Cash alternative | ✅ VIABLE |
| 6 | **Volatility-Scaled Momentum Score (E19)** | TheOmniscientParadox | Medium | Low | **HIGH** | Condition #7 mod | ✅ VIABLE |
| 7 | **Benchmark Fallback (E25)** | IRPrecisionFalcon | Medium | Low | Medium | Cash alternative | ✅ VIABLE |

### Deferred Ideas (Low Priority)

| Idea | Source | Reason |
|------|--------|--------|
| High-Confidence Gate (E24) | IRPrecisionFalcon | Already score=8 exists |
| Per-Position Stop Loss (E29) | DualMomentumTechStocks | Conflicts with Kijun stop |
| RSI Overbought Gate (E30) | ConditionalSectorRotation | Contradicts trend-following |
| SPY SMA200 Regime (E31) | ConditionalSectorRotation | Cloud already handles this |
| Leveraged ETF Universe (E32) | ConditionalSectorRotation | Already tested, rejected |
| ML Signal Overlay (E23) | IRPrecisionFalcon | Too complex, low interpretability |
| RSI Extreme Avoidance (E21) | TheOmniscientParadox | Mean-reversion vs trend-following |

### Top 3 Recommendations

**1. E26 — Inverse Volatility Sizing (DualMomentumTechStocks)**
- **Implementation:** Replace flat 10% sizing with `position_pct = base_pct / (vol / median_vol)`
- **Expected Impact:** Reduce risk concentration, improve risk-adjusted returns
- **Rationale:** Proven in DualMomentumTechStocks; BCT lacks position-level risk management

**2. E22 — Benchmark-Relative Active Return Filter (IRPrecisionFalcon)**
- **Implementation:** Pre-filter: only consider stocks with 10d active return (vs SPY) > 0
- **Expected Impact:** Reduce false breakouts, improve win rate
- **Rationale:** Avoid entering stocks underperforming benchmark despite technical patterns

**3. E27 — Monthly Momentum Ranking Pre-Filter (DualMomentumTechStocks)**
- **Implementation:** Sort universe by 90d momentum, take top 100 before BCT scoring
- **Expected Impact:** Faster backtests, baseline trend quality
- **Rationale:** Ensures all candidates have positive momentum tailwind

**Experiment Priority:**
- Phase 1: E26 (vol sizing) — standalone, clear hypothesis
- Phase 2: E22 + E26 combined — active return filter + vol sizing
- Phase 3: E27 — if performance improves, consider as coarse filter replacement

---

## Analysis Notes

### TheOmniscientParadox Failure Analysis
- **Why it ranked #1 on QC but failed OOS:** 51.5% drawdown indicates overfit to 2020-2021 bull market
- **BCT lesson:** Volatility-scaling alone insufficient; need trend regime context (weekly cloud)
- **Key insight:** Multi-horizon momentum (E20) is valuable; volatility-scaling (E19) needs cloud context

### IRPrecisionFalcon Success Factors
- **Benchmark-relative framing:** Critical for stock selection (avoid false absolute breakouts)
- **High-confidence gating:** 70% probability threshold reduces false signals
- **Machine learning:** Less critical than the benchmark-relative feature engineering
- **BCT lesson:** Active return vs SPY is a powerful pre-filter

### DualMomentumTechStocks Key Insights
- **Inverse vol sizing:** Simple but effective risk management BCT lacks
- **90d momentum pre-filter:** Ensures baseline trend quality
- **GLD cash substitute:** Smart cash management during signal droughts
- **BCT lesson:** Position sizing by volatility, not equal-weight, should improve Sharpe

### ConditionalSectorRotation Assessment
- **Leveraged ETFs + RSI timing:** High-risk, high-reward but overfit-prone
- **SPY SMA200 regime:** Redundant with BCT weekly cloud
- **RSI extremes:** Mean-reversion signals conflict with BCT trend-following
- **BCT lesson:** Skip — EXP-ETF experiments (#67-69) already proved equity-only superior

---

## Conclusion

**4 strategies analyzed, 14 ideas extracted, 7 viable, 3 recommended.**

**Biggest Gap in BCT:** Position sizing (flat 10% vs risk-adjusted)  
**Best Addition:** E26 Inverse Volatility Sizing — simple, proven, high impact

**Next Step:** HQ decision on E26 experiment design

---

*Generated: 2026-05-27 by 2dfwm2xd*  
*Updated: 2026-05-27 (all 4 strategies complete)*  
*Status: P1 Analysis Complete — awaiting HQ direction on E22/E20 implementation*
