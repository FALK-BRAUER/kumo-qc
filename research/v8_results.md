# V8 Results: Sector-Specific Regime Gates (GH #135)

## Experiment: V8
- **Change:** Per-symbol entry gated by sector ETF > 50-day MA (replaces single QQQ > 50MA gate)
- **Branch:** feat/e40c-v3 (detached from 3b1c244)
- **Commit:** 42916e5
- **Rationale:** Sector-specific regime filters may avoid entering weak sectors while allowing strong ones

## W1-W6 Rolling Window Results

| Window | Period | Sharpe | Orders | Net Profit | DD | Win Rate |
|--------|--------|--------|--------|------------|-----|----------|
| W1 | Jan-Jun 2025 | **-1.310** | 161 | -8.634% | 14.300% | 22% |
| W2 | Feb-Jul 2025 | **-0.877** | 133 | -4.895% | 14.100% | 23% |
| W3 | Mar-Aug 2025 | **-0.713** | 137 | -4.468% | 11.900% | 27% |
| W4 | Apr-Sep 2025 | **0.411** | 127 | 7.143% | 7.600% | 32% |
| W5 | May-Oct 2025 | **1.127** | 89 | 13.809% | 7.300% | 52% |
| W6 | Jun-Nov 2025 | **0.198** | 117 | 5.106% | 7.600% | 33% |

**Screen gate: 3/6 windows positive (50%) — FAILS 4+/6 criteria. FY2025 NOT RUN.**

## Key Observations

1. **Catastrophic early-year performance:** W1-W3 all deeply negative (-1.31, -0.877, -0.713)
   - Sector gates over-blocked in Jan-Jun 2025
   - Tech sector (XLK) below 50MA for extended periods, blocking AAPL/MSFT/NVDA entries
   - Meanwhile other sectors also weak, creating near-total entry blockage + whipsaw

2. **Late-year recovery:** W4-W5 positive (0.411, 1.127) — sector dispersion worked when trends were strong

3. **Win rate collapse:** Early year 22-27% vs baseline ~40%. Sector gate too sensitive.

4. **Drawdown doubled:** 14.3% vs e40c ~8-10%. Sector whipsaws create cumulative losses.

## Comparison to Baselines

| Experiment | W1 Sharpe | FY2025 Sharpe | Notes |
|------------|-----------|---------------|-------|
| e40c (champion) | 0.984 | 0.778 | QQQ > 50MA single gate |
| V8 (sector gates) | **-1.310** | N/A (screen fail) | Per-sector > 50MA |

## Verdict: REJECTED — SCREEN FAIL

V8 sector-specific regime gates **fail the W1-W6 screen** (3/6 positive, required 4+/6).

Root cause: Per-sector 50MA gates are **too granular** and create whipsaw in volatile periods. When multiple sectors are below 50MA simultaneously (early 2025), the system either:
- Blocks too many entries (missing recovery bounces)
- Or enters only the weakest mean-reverting sectors

Single-index regime gate (QQQ/SPY > 50MA or 200MA) is more robust because it uses broader market momentum rather than noisy sector-level signals.

**Recommendation:** Do not pursue sector-specific regime gates. E40c (single QQQ > 50MA) remains the regime gate champion.
