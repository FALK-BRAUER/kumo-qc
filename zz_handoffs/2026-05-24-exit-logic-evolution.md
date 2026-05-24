# Exit Logic Evolution

## Comparison Table

| Aspect              | Reference Algorithm (Sharpe 0.393) | Current Algorithm (3 Exits) |
|---------------------|------------------------------------|-------------------------------|
| Exit Conditions     | Daily Kijun Stop                     | Daily Kijun Stop, Cloud Top Exit, Weekly Kijun Trail Exit |
| Entry Logic         | ≥7/8 BCT signal entry                | ≥7/8 BCT signal entry           |
| Universe Filter     | Coarse filter 6k → ~200 by price + liquidity | Coarse filter 6k → ~200 by price + liquidity |

## Impact of Added Exits

- **Cloud Top Exit**: More exits, likely lower trade count.
- **Weekly Kijun Trail Exit**: Even more exits, further reducing trade count.

## Recommendation

- **Option 1**: Run reproduction with current code (3 exits) and accept different metrics.
- **Option 2**: Create a "reference-compatible" mode with only the Kijun stop to match original backtest metrics.
