# V2 QQQ Dual MA (50+200) Window Results — vs e40c Baseline

**Gate:** QQQ price must be > 50-day MA AND > 200-day MA to allow entries.
**Baseline:** e40c FY2025 Sharpe = 0.778

## Rolling 6-Month Windows (2025)

| Window | Period | Sharpe | Orders | DD | Win% | Return | Status |
|--------|--------|--------|--------|-----|------|--------|--------|
| W1 | Jan-Jun | **0.675** | 63 | 9.0% | 44% | 19.835% | ✅ POS |
| W2 | Feb-Jul | **-0.025** | 65 | 6.1% | 29% | 7.221% | ❌ NEG |
| W3 | Mar-Aug | **-0.140** | 65 | 6.3% | 46% | 5.302% | ❌ NEG |
| W4 | Apr-Sep | **0.669** | 75 | 6.3% | 42% | 17.643% | ✅ POS |
| W5 | May-Oct | **0.524** | 97 | 6.3% | 39% | 16.186% | ✅ POS |
| W6 | Jun-Nov | **-0.161** | 121 | 7.6% | 32% | 3.288% | ❌ NEG |

**Positive windows:** 3/6 (W1, W4, W5)
**FY2025 run threshold:** Requires 4+/6 windows positive → **NOT MET**

## Summary
- V2 dual-MA confirmation is **more restrictive** than e40c (QQQ>200MA only)
- Blocks entries during periods when QQQ is between 50MA and 200MA
- Results: mixed — 3 windows positive but 3 negative, including W6 (largest window, most orders)
- **Verdict:** Does not improve on e40c baseline. Rejected for FY2025 full run.
