# Parity Results Table
*Last updated: 2026‑05‑24*

## Context
- W4‑W6 cloud backtests re‑run after lean cloud push (ktki1gjz)
- ETF filter intentional — ETFs bypass coarse filter via AddEquity
- W1/FY2025 zero trades due to warmup_days mismatch (182 vs 750)
- Baseline‑exits‑on‑2020‑2026 target: Sharpe 0.493, trades 71
- QC Researcher tier limit 2 concurrent backtests → sequential submission

## Parity Status — Rerun Order
- W1 → W2 → W3 → W6 → FY2025 sequential (warmup_days=200 for short windows, 750 for FY2025)
- Local parity parked due to Morningstar data unavailable

| Window | Sharpe | Trades | Net Profit | CAGR | Max DD |
|--------|--------|--------|------------|------|--------|
| W4 | 16.118 | 10 | 0 | 0 | 0 |
| W5 | -2.922 | 12 orders / 1 trade | -2.223% | -87.149% | 3.000% |
| W1 (0a35ed3beb5042b67af0a0790ad87442) | In Progress… (0.102) | pending | pending | pending | pending |
| FY2025 (old) | Invalid timestamp | 0 | 0 | 0 | 0 |
| FY2025 (old) | Runtime Error (warmup mismatch, 182) | 0 | 0 | 0 | 0 |
| W2‑W6 | pending | pending | pending | pending | pending |

## Backtest IDs
- W4: be3e8b65c6d578d9e287edd0a2dde8ba (not found in API)
- W5: 3e7eba1118f70470a2ed6973a7861b7a
- W1: 24b9bc4ecad772cec83c41d07783da15
- FY2025 (new): b166eed8d02c1581a2676875f7f2e3d2 (warmup_days=182)
- Baseline‑exits‑on‑2020‑2026: c58e0e99e0322e6230b51a86e0179b43 (not found)

## ETF Filter Design
ETFs bypass coarse filter via AddEquity lines 54‑56 in `algorithm/performance_bct/main.py`. Intentional design — no bug.

## Warmup Mismatch
Weekly Ichimoku seeding requires 750 days warmup (default). Current FY2025 and W1 submissions use 182 days (insufficient). Leads to Runtime Error, zero trades.

## QC Limits
Researcher tier allows 2 concurrent backtests. W2‑W6 capacity errors → sequential submission after W1 slot freed.

## Next Steps
- Wait for ktki1gjz clean lean cloud push
- Wait for FY2025 re‑submit with warmup_days=750
- Wait for W2‑W6 sequential submission
- Poll each backtestId for stats
- Update parity table