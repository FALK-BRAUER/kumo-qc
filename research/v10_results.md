# V10 Regime-Scaled Positions (GH #137) — Window Results

**Concept:** Instead of binary block when QQQ < 50-day MA, scale position size
to half (5% vs 10%). Full size when QQQ > 50MA.
**Baseline:** e40c flat W1 Sharpe = 0.984

## Rolling 6-Month Windows (2025)

| Window | Period | Sharpe | Orders | DD | Win% | Return | Status |
|--------|--------|--------|--------|-----|------|--------|--------|
| W1 (Jan-Jun) | -1.242 | 302 | 23.0% | 24% | -20.222% | ❌ |
| W2 (Feb-Jul) | -1.484 | 267 | 20.3% | 22% | -21.661% | ❌ |
| W3 (Mar-Aug) | -1.193 | 259 | 17.4% | 22% | -18.871% | ❌ |
| W4 (Apr-Sep) | **0.477** | 199 | 10.4% | 29% | 16.627% | ✅ |
| W5 (May-Oct) | **2.478** | 78 | 7.4% | 51% | 67.068% | ✅ |
| W6 (Jun-Nov) | -0.021 | 127 | 7.6% | 32% | 6.065% | ❌ |

**Positive windows:** 2/6 (W4, W5)
**Threshold:** 4+/6 required → **NOT MET**

## Analysis
- **W1-W3 catastrophic:** During QQQ < 50MA periods, half-size entries still lose money rapidly. The regime gate exists for a reason — weak-regime entries are toxic regardless of size.
- **W5 exceptional:** Strong trending market with QQQ > 50MA throughout. Full-size positions capture full upside. Sharpe 2.478 is excellent.
- **Order count variance:** W1-W3 show 250-300 orders (high churn from stop-outs during weak regime), W5 only 78 orders (clean trending environment).
- **Scaling doesn't help:** Half-size losses in weak regime still compound to large drawdowns (17-23%). The problem is direction, not size.

## Verdict
**REJECTED.** Regime-scaled sizing fails 4/6 windows. The binary block (e40c) is correct — weak-regime entries should be avoided entirely, not merely reduced.
