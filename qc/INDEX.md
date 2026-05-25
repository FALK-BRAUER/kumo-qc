# QC Strategy Index
*Last updated: 2026-05-25*

## Phase 1 Parity Baseline (minimal_bct)

| Run | Universe | Period | Sharpe | CAGR | MaxDD | Trades | Win% |
|-----|----------|--------|--------|------|-------|--------|------|
| LOCAL | SPY+QQQ+AAPL | FY2020 | 1.177 | 12.851% | 8.2% | 47 | 45% |
| CLOUD (32099988) | SPY+QQQ+AAPL | FY2020 | 1.183 | 12.968% | 8.3% | 47 | 45% |

Delta: +0.12% CAGR, +0.006 Sharpe — parity confirmed. Config: LocalDiskMapFileProvider + LocalDiskFactorFileProvider + DefaultDataProvider.

## QC Cloud Backtests (performance_bct / backtest_bct)

| # | Name | Project | Sharpe | CAGR | MaxDD | Trades | Win% | Status |
|---|------|---------|--------|------|-------|--------|------|--------|
| 1 | bct-perf-2020-2026 | performance_bct | 0.393 | 14.253% | — | 1807 | 42% | ✅ Downloaded |
| 2 | bct-perf-native-ichi-2020-2026 | performance_bct | 0.278 | 9.976% | — | 1884 | 42% | ✅ Downloaded |
| 3 | perf-W1 (68.4 Sharpe) | performance_bct | 68.417 | — | — | 11 | — | ✅ Downloaded |
| 4 | perf-W2 | performance_bct | 322.099 | — | — | 10 | — | ✅ Downloaded |
| 5 | perf-W3 | performance_bct | 28.026 | — | — | 10 | — | ✅ Downloaded |
| 6 | perf-W4 | performance_bct | 16.118 | — | — | 10 | — | ✅ Downloaded |
| 7 | perf-W5 | performance_bct | -2.922 | — | — | 12 | — | ✅ Downloaded |
| 8 | perf-FY2025 (multiple runs) | performance_bct | — | — | — | — | — | ⏳ 0 trades — warmup mismatch |
| 9 | BCT FY2025 Signal Audit | backtest_bct | — | — | — | — | — | ✅ Downloaded |

## W1-W3 QC Cloud Results (2026-05-24 session, warmup_days=5)

| Window | Dates | Sharpe | CAGR | MaxDD | Trades | Notes |
|--------|-------|--------|------|-------|--------|-------|
| W1 | 2026-05-20 to 2026-05-23 | 68.417 | 2400.4% | 0.7% | 11 | warmup_days=5 |
| W2 | 2026-05-16 to 2026-05-19 | 322.099 | 4338.5% | 0% | 10 | warmup_days=5 |
| W3 | 2026-05-13 to 2026-05-15 | 28.026 | 297.3% | 0% | 10 | warmup_days=5 |
| W4 | 2026-04-28 to 2026-05-02 | 16.118 | — | — | 10 | completed |
| W5 | 2026-05-05 to 2026-05-09 | -2.922 | — | — | 12 | completed |
| W6 | 2026-05-12 to 2026-05-16 | — | — | — | — | completed, stats not in folder |

## Open Items

- FY2025 full-year: needs re-run with warmup_days=100 (window=365d, warmup must be < 365)
- W6 stats: completed on QC cloud but not in qc/ folder stats
- run_perf_windows.py warmup=750 will re-break W1-W3 (4-day windows) — needs per-window logic

Status values: `✅ Downloaded` | `⏳ To process` | `❌ Failed`
