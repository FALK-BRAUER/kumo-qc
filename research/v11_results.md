# V11 Results: Volatility-Scaled Sizing (GH #138)

## Experiment: V11
- **Change:** Scale POSITION_PCT by VIX trend — when VIX rising (today > 5d ago), use 0.5x size
- **Branch:** feat/e40c-v3 (detached from 3b1c244, base e40c)
- **Commit:** 5cf728c
- **Rationale:** Reduce exposure during volatility expansion periods

## W1-W6 Rolling Window Results

| Window | Period | Sharpe | Orders | Net Profit | DD | Win Rate |
|--------|--------|--------|--------|------------|-----|----------|
| W1 | Jan-Jun 2025 | 0.511 | 100 | 7.614% | 7.900% | 40% |
| W2 | Feb-Jul 2025 | 0.240 | 93 | 5.149% | 7.100% | 33% |
| W3 | Mar-Aug 2025 | 0.616 | 87 | 8.087% | 6.100% | 36% |
| W4 | Apr-Sep 2025 | 2.515 | 99 | 24.157% | 6.100% | 38% |
| W5 | May-Oct 2025 | 2.373 | 120 | 25.762% | 6.100% | 41% |
| W6 | Jun-Nov 2025 | 0.836 | 153 | 10.426% | 5.700% | 37% |

**Screen: 6/6 windows positive (100%) — PASSES 4+/6 gate.**

## FY2025 Full Window Results

| Metric | Value |
|--------|-------|
| Sharpe Ratio | 0.531 |
| Total Orders | 240 |
| Net Profit | 16.260% |
| Max Drawdown | 7.900% |
| Win Rate | 44% |

## Comparison to Baselines

| Experiment | FY2025 Sharpe | Notes |
|------------|---------------|-------|
| e40c (champion) | 0.778 | QQQ > 50MA regime gate, flat 10% sizing |
| **V11 (vol-scaled)** | **0.531** | 0.5x size when VIX rising |
| **Delta** | **-0.247** | Significant underperformance |

## Key Observations

1. **W1-W6 all positive** — volatility scaling avoids some downside, but...
2. **FY2025 Sharpe degraded** — 0.531 vs 0.778 (delta -0.247)
3. **Fewer orders per window** — 87-153 vs e40c ~150-200 (more selective due to smaller sizes)
4. **Lower drawdown** — 5.7-7.9% vs e40c ~8-10%, but Sharpe still worse
5. **Win rate lower** — 33-44% vs e40c ~40-46%

## Verdict: REJECTED

V11 volatility-scaled sizing **underperforms e40c baseline** (0.531 vs 0.778).

Root cause: The 0.5x reduction when VIX rises is **too conservative**. During VIX spikes (which often coincide with market bottoms), the reduced position sizes:
- Miss the full upside of recovery rallies
- Create smaller absolute gains that don't compensate for reduced downside
- The Sharpe degradation (-0.247) shows the risk reduction is not worth the return sacrifice

**Recommendation:** Flat sizing (10% POSITION_PCT) remains optimal. Dynamic sizing based on VIX trend degrades risk-adjusted returns.
