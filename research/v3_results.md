# V3 Results: SPY > 50-day MA Regime Gate (GH #130)

## Experiment: E40c-v3
- **Change:** SPY > 50-day SMA regime gate (was SPY > 200-day SMA in E40b)
- **Branch:** feat/e40c-v3
- **Commit:** (pending)
- **Rationale:** 50-day MA responds faster to regime changes than 200-day MA

## W1-W6 Rolling Window Results

| Window | Period | Sharpe | Orders | Net Profit | DD | Win Rate | Regime Blocks |
|--------|--------|--------|--------|------------|-----|----------|---------------|
| W1 | Jan-Jun 2025 | 0.794 | 71 | 9.821% | 7.600% | 42% | 81 |
| W2 | Feb-Jul 2025 | 0.155 | 73 | 4.594% | 6.300% | 28% | 66 |
| W3 | Mar-Aug 2025 | 0.831 | 61 | 10.151% | 7.400% | 46% | 61 |
| W4 | Apr-Sep 2025 | **2.864** | 66 | **29.515%** | 7.400% | 48% | 30 |
| W5 | May-Oct 2025 | **2.478** | 78 | **29.469%** | 7.400% | 51% | 0 |
| W6 | Jun-Nov 2025 | -0.161 | 121 | 1.613% | 7.600% | 32% | 8 |

**Verdict: 5/6 windows > 0 (83%) → FY2025 full run AUTHORIZED per dispatch criteria**

## Key Observations

1. **Summer surge:** W4 (Apr-Sep) and W5 (May-Oct) show exceptional Sharpe (2.864, 2.478) with ~30% returns
2. **Early year weakness:** W1-W2 show mediocre performance (0.794, 0.155) with high regime block counts (81, 66)
3. **Late year collapse:** W6 (Jun-Nov) negative (-0.161) — 50MA too whipsaw-sensitive in Q4 2025
4. **Regime block count declines:** 81 → 66 → 61 → 30 → 0 → 8 (SPY above 50MA more often in summer)

## Comparison to Baselines

| Experiment | FY2025 Sharpe | Notes |
|------------|---------------|-------|
| E40d (champion) | 1.442 | Current baseline |
| E40b (SPY>200MA) | 1.048 | Slower regime |
| **E40c-v3 (SPY>50MA)** | **0.638** | Faster regime, more blocks early/late |

## FY2025 Full Window Results

| Metric | Value |
|--------|-------|
| Sharpe Ratio | 0.638 |
| Total Orders | 149 |
| Net Profit | 19.949% |
| Max Drawdown | 8.700% |
| Win Rate | 46% |
| Delta vs E40d | **-0.804** |

## Verdict: REJECTED

E40c-v3 (SPY > 50-day MA) is **REJECTED**. FY2025 Sharpe 0.638 vs E40d 1.442 (delta -0.804).

The 50-day MA regime gate is **too sensitive**:
- Blocks 81 days in W1 (Jan-Jun), missing early-year trending entries
- Allows too much exposure in W6 (Jun-Nov), catching late-year drawdowns
- Summer windows (W4-W5) are strong but insufficient to offset early/late weakness
- The faster response of 50MA creates whipsaw losses — exits and re-entries on minor SPY corrections

**Recommendation:** 200-day MA (E40b) remains superior to 50-day MA for regime gating. E40d (VIX-based) remains champion.
