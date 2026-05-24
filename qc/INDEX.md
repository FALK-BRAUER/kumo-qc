# QC Strategy Index
*Last updated: 2026-05-24*

## Performance backtests (project 32034565)
| # | Name | Sharpe | CAGR | Max DD | Trades | Win% | Status |
|---|---|---|---|---|---|---|---|
| 01 | bct-perf-2020-2026 | 0.393 | 14.253% | 40.900% | 1807 | 42% | ✅ Downloaded |
| 02 | bct-perf-native-ichi-2020-2026 | 0.278 | 9.976% | 33.700% | 1884 | 42% | ✅ Downloaded |

### W1-W6 + FY2025 window results — Additional tests fetched 2026-05-24
| Name | Sharpe | CAGR | Trades | Status |
|---|---|---|---|---|
| perf-W1 | 8.427 | 0% | 10 | ✅ Downloaded |
| perf-FY2025 | 0.801 | 0% | 44 | ✅ Downloaded |
| perf-W1 (2nd) | 0.733 | 0% | 28 | ✅ Downloaded |
| perf-W6 | 0.485 | 0% | 36 | ✅ Downloaded |
| perf-FY2025 (2nd) | 0.383 | 0% | 27 | ✅ Downloaded |
| perf-W5 | 0.337 | 0% | 36 | ✅ Downloaded |
| perf-W2 | 0.258 | 0% | 29 | ✅ Downloaded |
| perf-W3 | 0.195 | 0% | 33 | ✅ Downloaded |
| perf-W4 | 0.153 | 0% | 30 | ✅ Downloaded |

### W1-W6 + FY2025 window results (fixed score_symbol_native, 2026-05-24)
| Window | Period | NetProfit | Sharpe | Trades | Notes |
|---|---|---|---|---|---|
| W1 | 2026-04-07→11 | +31.044% | 0.733 | 28 | ✅ |
| W2 | 2026-04-14→18 | +12.482% | 0.258 | 29 | ✅ |
| W3 | 2026-04-22→25 | n/a | n/a | 0 | No trades — MIN_SCORE=7 filtered all (4-day tariff-shock window) |
| W4 | 2026-04-28→05-02 | +8.973% | 0.153 | 30 | ✅ |
| W5 | 2026-05-05→09 | +14.899% | 0.337 | 36 | ✅ |
| W6 | 2026-05-12→16 | +21.846% | 0.485 | 36 | ✅ |
| FY2025 | 2025-01-01→12-31 | +33.134% | **0.801** | 44 | ✅ Strong — 2× prior bct-perf-2020-2026 Sharpe |

## Signal audit / parity (project 32033824) — no trades, signal log only
| # | Name | Backtest ID | Period | Status |
|---|---|---|---|---|
| 03 | BCT FY2025 Signal Audit (FY) | `08c94422…` | 2025 (20d, node limit) | ✅ Downloaded |
| 04 | W1 2026-04-07→11 | `7c5224050c9369159da7a5f9c6f06140` | 5d | ✅ Logs fetched |
| 05 | W2 2026-04-14→18 | `c9c25d128d7b7f20175ce9c6c3b5bda1` | 5d | ✅ Logs fetched |
| 06 | W3 2026-04-22→25 | `8dbb076634baa7ac6cd8b3c2a457820f` | 5d | ✅ Logs fetched |
| 07 | W4 2026-04-28→5-2 | `5e6c60f071310c6aa96e2b40c5ec532d` | 5d | ✅ Logs fetched |
| 08 | W5 2026-05-05→09 | `78b3d1fa80786e34d538510537fcc605` | 5d | ✅ Logs fetched |
| 09 | W6 2026-05-12→16 | `bdbf24a9f5bec532e964311453767aa4` | 5d | ✅ Logs fetched |

## Local validation (scripts/local_backtest.py vs scanner_results)
| Period | Recall | Precision | Notes |
|---|---|---|---|
| W1 2026-04-07→11 | 98.1% | 12.6% | FPs = universe size delta (6737 vs ~250); C7/ADX 90% = data feed delta |
| W1-W6 full | 98.9% | 9.8% | 29 trading days; C7/ADX 94% (data feed delta Yahoo vs QC) |

Status values: `✅ Downloaded` | `✅ Logs fetched` | `⏳ To process` | `❌ Failed`