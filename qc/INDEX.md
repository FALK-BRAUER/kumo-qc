# QC Strategy Index
*Last updated: 2026-05-24*

## Performance backtests (project 32034565)
| # | Name | Sharpe | CAGR | Max DD | Trades | Win% | Status |
|---|---|---|---|---|---|---|---|
| 01 | bct-perf-2020-2026 | 0.393 | 14.253% | 40.900% | 1807 | 42% | ✅ Downloaded |
| 02 | bct-perf-native-ichi-2020-2026 | 0.278 | 9.976% | 33.700% | 1884 | 42% | ✅ Downloaded |

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
| W1-W6 full | ⏳ running | — | — |

Status values: `✅ Downloaded` | `✅ Logs fetched` | `⏳ To process` | `❌ Failed`