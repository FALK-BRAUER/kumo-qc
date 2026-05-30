# V7 Results — Wider Kijun Stops (3% buffer) (GH#134)

Base: e40c QQQ>50MA regime gate + V7 Kijun stop with 3% buffer (exit if close < kijun×0.97).
All runs verified with VERSION_MARKER|v7_wider_stop.

## Rolling 6-Month Windows (FY2025)

| Window | Period      | Sharpe | Orders | Net Profit | Drawdown | Win Rate |
|--------|-------------|--------|--------|------------|----------|----------|
| W1     | Jan-Jun     | 0.562  | 52     | 7.78%      | 9.7%     | 38%      |
| W2     | Feb-Jul     | 0.218  | 48     | 5.10%      | 8.9%     | 26%      |
| W3     | Mar-Aug     | 0.159  | 37     | 4.70%      | 6.5%     | 50%      |
| W4     | Apr-Sep     | 0.987  | 45     | 11.68%     | 6.5%     | 44%      |
| W5     | May-Oct     | 0.913  | 58     | 12.24%     | 7.1%     | 36%      |
| W6     | Jun-Nov     | 1.480  | 50     | 16.32%     | 5.2%     | 19%      |
| **FY2025** | Jan-Dec | **0.073** | **104** | **8.11%** | **9.7%** | **40%** |

## Comparison vs Baselines

| Metric     | V7     | e40c (orchestrator) | e40c (bt-results) |
|------------|--------|---------------------|-------------------|
| Sharpe     | 0.073  | 0.778               | 1.362             |
| Orders     | 104    | —                   | 166               |
| Net Profit | 8.11%  | —                   | 37.5%             |
| Drawdown   | 9.7%   | —                   | 9.2%              |
| Win Rate   | 40%    | —                   | 45%               |

## Interpretation

V7 (3% buffer below Kijun) also collapses full-year performance to near-zero Sharpe (0.073).
The wider stop prevents timely exits, allowing drawdown to accumulate across windows.
W4-W6 are individually strong (0.987, 0.913, 1.480) because the buffer avoids
whipsaws during strong trending periods. But W1-W3 are too weak to carry the year.

Combined with V12 (no stop first 5 days → 0.001 Sharpe), this confirms:
**The fast Kijun stop IS the protective edge. Any loosening — whether temporal
skip or price buffer — destroys risk-adjusted full-year returns.**

Verdict: **REJECTED** — wider Kijun stops do not improve e40c.
