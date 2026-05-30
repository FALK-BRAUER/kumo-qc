# V12 Results — No Kijun Stop First 5 Days (GH#139)

Base: e40c QQQ>50MA regime gate + V12 Kijun-stop skip if days_held < 5.
All runs verified with VERSION_MARKER|v12_no_stop_first5d.

## Rolling 6-Month Windows (FY2025)

| Window | Period      | Sharpe | Orders | Net Profit | Drawdown | Win Rate |
|--------|-------------|--------|--------|------------|----------|----------|
| W1     | Jan-Jun     | 0.317  | 63     | 5.82%      | 7.8%     | 41%      |
| W2     | Feb-Jul     | 0.338  | 67     | 5.97%      | 8.0%     | 34%      |
| W3     | Mar-Aug     | 0.632  | 61     | 8.26%      | 7.0%     | 46%      |
| W4     | Apr-Sep     | 2.197  | 69     | 21.25%     | 7.0%     | 47%      |
| W5     | May-Oct     | 1.636  | 87     | 18.69%     | 7.0%     | 46%      |
| W6     | Jun-Nov     | 0.787  | 102    | 11.54%     | 6.2%     | 30%      |
| **FY2025** | Jan-Dec | **0.001** | **163** | **6.92%** | **9.6%** | **40%** |

## Comparison vs Baselines

| Metric     | V12    | e40c (bt-results) | Delta   |
|------------|--------|-------------------|---------|
| Sharpe     | 0.001  | 1.362             | -1.361  |
| Orders     | 163    | 166               | -3      |
| Net Profit | 6.92%  | 37.5%             | -30.6%  |
| Drawdown   | 9.6%   | 9.2%              | +0.4%   |
| Win Rate   | 40%    | 45%               | -5%     |

## Interpretation

V12 (no Kijun stop first 5 days) collapses full-year performance. 
The anti-whipsaw modification appears to prevent necessary early exits,
allowing losing positions to accumulate drawdown that later profitable
windows cannot recover within the same FY.

W4 and W5 show strong individual Sharpe (2.197, 1.636) because the skip
aligns with strong trending periods where early Kijun exits would have
been premature. However, W1-W3 and W6 suffer enough that FY2025 net is flat.

Verdict: **REJECTED** — the 5-day Kijun grace period destroys full-year
risk-adjusted returns despite helping selected windows.
