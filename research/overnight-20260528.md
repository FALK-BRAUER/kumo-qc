# Overnight Research Findings — 2026-05-28

## 1. bt-results.csv Pattern Analysis — Regime Gates Are the ONLY Positive Axis

**Total experiments analyzed:** 59 (E1-E44 + ETF-1 + variants)
**Positive results:** 3 (E40b-v2, E40c, E40d) — ALL regime gates
**Negative/neutral:** 56 — everything else

### What Positive Experiments Share
All positive experiments are **pre-entry macro filters** that reduce the denominator (bad entries):
- E40b-v2: SPY > 200MA ≥3d consecutive → 1.463 Sharpe
- E40c: QQQ > 50MA → 1.362 Sharpe
- E40d: VIX < 25 → 1.442 Sharpe (champion)

### What Rejected Experiments Attempted
All operate **after** entry decision, trying to optimize the numerator:
- Exit modifications (E36 ATR stop, E39 ladder exits, E41 ADX plateau): 0.947, 0.470, -0.333
- Sizing (E42 risk-based, E44 heat cap): -0.375, 0.856
- Universe (ETF-1): 0.967, 0.880
- Entry gates (E38 resistance): 0.565
- ADX modifications (E41 all variants): -0.333 to 0.273

### Underlying Principle
**BCT's edge is in avoiding losers, not picking bigger winners.**
The 8-condition BCT scorer already identifies strong trends. The problem is noise entries during weak market regimes. Regime gates filter these at the macro level before technical scoring even matters.

**Implication:** Future experiments should focus on regime gate variations, not entry/exit/sizing/universe modifications.

---

## 2. QC Community Strategy Analysis — Already Completed by 2dfwm2xd

**File:** `research/qc_strategy_analysis_bct_ideas.md`

### Key Finding: 7 untested ideas extracted, top 3 recommended:
1. **E26 — Inverse Volatility Sizing:** Scale position by 1/σ — NOT YET TESTED
2. **E22 — Benchmark-Relative Active Return Filter:** Only enter if 10d active return vs SPY > 0 — NOT YET TESTED
3. **E27 — Monthly Momentum Ranking Pre-Filter:** Top 100 by 90d momentum before BCT scoring — NOT YET TESTED

**Verdict:** Research-recommended ideas are fresh — none overlap with tested experiments. However, they violate the principle above (they're post-entry optimizations, not regime gates). Priority: test only if regime gate queue exhausted.

---

## 3. Ichimoku Literature Search

**Sources searched:** arXiv, web (quantifiedstrategies.com, trendspider, stockcharts)

### Findings:
- **Chikou span confirmation:** Widely discussed but no rigorous backtests found. Academic papers cite it as sentiment gauge, not entry signal.
- **Cloud thickness entry filter:** Thicker cloud = stronger support/resistance. Could be added as soft gate (avoid entries when cloud is thin).
- **Tenkan/Kijun cross as secondary entry:** Tradinformed (2014) shows it as standalone strategy. Not tested as BCT add-on.
- **No academic evidence** that Ichimoku exit variations outperform simple trend-following stops.

**Verdict:** Literature does not suggest any untested Ichimoku variations with strong evidence. BCT's 8-condition stack is already more sophisticated than most published strategies.

---

## 4. S&P 500 Survivorship Bias in Polygon-326 — ⚠️ CRITICAL FINDING

**Analysis date:** 2026-05-28
**Data sources:** `polygon_universe_equity200_fy2025.json` vs `sp500_universe_fy2025.json`

**⚠️ FLAG:** E40d's 1.442 Sharpe may be PARTLY INFLATED by momentum-biased universe selection, not purely strategy quality. Polygon-326 is a "momentum-filtered subset" — NOT a "representative universe." S&P 500 BT (#103) is the clean validation.

### Key Findings:

**Dynamic composition:**
- 326 total unique tickers across FY2025
- 79 tickers (24%) added after 2025-03-01 — late additions suggest momentum-driven selection
- 86 tickers (26%) present <50 days — brief appearances indicate unstable filtering

**Index membership mismatch:**
- 33 tickers in polygon but NOT in S&P 500 — includes meme/momentum names:
  - GME, MARA, CLSK, CELH, CHWY, CAVA, DOCU, DUOL, ENPH, ETSY
- 207 tickers in S&P 500 but NOT in polygon — we're missing 40% of the index

**Selection bias mechanism:**
Polygon-326 is filtered by "top 200 by dollar volume" — this creates a momentum/sentiment bias:
- Names with volume spikes (meme stocks, short squeezes) enter the universe
- Names in quiet accumulation (strong fundamentals, low volume) are excluded
- Post-2022 additions likely benefited from 2023-2024 AI/tech rally (selection bias for recent winners)

**Implications:**
1. **S&P 500 experiment (#103) is HIGHLY meaningful** — tests static index membership vs dynamic momentum filter
2. **Polygon-326 Sharpe may be inflated** by momentum bias (more volatile names = higher returns in bull markets)
3. **S&P 500 universe may have LOWER Sharpe but BETTER robustness** — less selection bias, more representative
4. **ALL future results disclosures must note:** "Polygon-326 is a momentum-filtered subset, not representative of the full S&P 500 or investable universe"
5. **E40d's 1.442 Sharpe** should be interpreted as "1.442 on a momentum-biased subset" until validated on S&P 500

---

## 5. Queue Status — Overnight Experiments Ready to Dispatch

### Created Tonight:
| Issue | Experiment | Type | Hypothesis |
|-------|-----------|------|------------|
| #96 | E53-v2 | Parameter sweep | Earnings ±2d |
| #97 | E53-v3 | Parameter sweep | Earnings ±1d |
| #98 | E40-combo | Regime gate | VIX+SPY stack |
| #99 | E36-v2 | Exit mod | ATR 1.5× |
| #100 | #85 | Entry gate | Signal freshness |
| #101 | #51 | Entry gate | Parabolic block |
| #102 | #87 | Entry gate | Rotation quality |
| #103 | E40d-sp500 | Universe | 500 vs 326 names |
| #104 | E40d-v3 | Regime gate | VIX<30 |
| #105 | E40f | Regime gate | HY credit >4% |
| #106 | E40d-v2 | Regime gate | VIX<20 |
| #107 | E40h | Regime gate | VVIX<100 |
| #108 | E40g | Regime gate | Breadth <50% |

### Total open experiment issues:** 13 (ready for dispatch when BT slots free)

---

## 6. Recommended Dispatch Order

**Priority 1:** Regime gate variations (E40d-v2, E40d-v3, E40f, E40g, E40h, E40-combo)
**Priority 2:** W7-YTD-2026 validation (confirm E40d in 2026)
**Priority 3:** S&P 500 universe (#103) — high value given survivorship bias finding
**Priority 4:** Parameter sweeps (E53-v2/v3, E36-v2)
**Priority 5:** New entry gates (#85, #51, #87) — lower priority per principle analysis
**Priority 6:** Research recommendations (E26, E22, E27) — only if regime gate queue exhausted

---

*Documented by: fintrack (Claude Code)
*Date: 2026-05-28
*Status: Complete — awaiting Falk/HQ dispatch authorization