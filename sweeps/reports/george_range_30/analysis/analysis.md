# George Range 30 Analysis

## Scope

This analysis uses only the completed local LEAN artifacts from `george_range_30`: summary rows, filled orders, paired/censored trades, and the decision tags embedded in entries. It does not infer sector, regime, gap-fill, or scanner-miss context that is not present in these CSVs.

## Best Observed Parameter Cells

| variant | family | net | DD | orders | sharpe | confidence |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `giveback_tight_no_bull` | exit_target | 10.960% | 17.600% | 257 | 0.569 | medium |
| `target_08_let_run` | exit_target | 10.330% | 17.700% | 223 | 0.530 | medium |
| `p_only_tight_giveback` | anchor | 10.292% | 17.400% | 326 | 0.535 | medium |
| `target_04_fast_take` | exit_target | 10.196% | 17.800% | 245 | 0.527 | medium |
| `p_only_base` | anchor | 10.118% | 17.300% | 243 | 0.526 | medium |
| `minpeak_low_03` | exit_target | 10.012% | 17.100% | 478 | 0.523 | medium |
| `giveback_loose_04` | exit_target | 9.957% | 17.300% | 259 | 0.517 | medium |
| `buy_stop_005` | entry_trigger | 8.058% | 15.900% | 1291 | 0.415 | high |

## Lowest Drawdown Cells

| variant | family | net | DD | orders | read |
| --- | --- | ---: | ---: | ---: | --- |
| `pos_03_atr_075` | risk_stack | 5.616% | 13.700% | 1870 | candidate DD control |
| `buy_stop_010` | entry_trigger | 7.099% | 15.800% | 1084 | candidate DD control |
| `buy_stop_005` | entry_trigger | 8.058% | 15.900% | 1291 | candidate DD control |
| `minpeak_low_03` | exit_target | 10.012% | 17.100% | 478 | context |
| `buy_stop_flat` | entry_trigger | 6.838% | 17.200% | 1483 | context |

## Parameter Confidence

| axis | best net | best <=18% DD | recommended range | confidence | interpretation |
| --- | --- | --- | --- | --- | --- |
| exit_target_management | `giveback_tight_no_bull` (10.960% / 17.600% DD) | `giveback_tight_no_bull` (10.960% / 17.600% DD) | target 6-8%, min_peak 3-5%, giveback 1.5-2.5%; test no-bullish-gate again | medium | Best risk-adjusted cells are all proactive exit variants near 10% net with <=18% DD. |
| scratch_no_progress | `scratch_1d_low_mfe` (6.950% / 18.100% DD) | `scratch_tight_risk` (6.053% / 17.600% DD) | Do not promote as primary edge; if kept, retest only tight-risk or 1d low-MFE. | medium | Scratch variants prove the path contract but consistently trail proactive-only return. |
| entry_near_pct | `entry_near_025` (7.588% / 18.500% DD) | `entry_near_010` (4.624% / 17.800% DD) | 2.0-2.5% only as a follow-up if paired with stronger exits/DD cap. | low | Wider near-zone raises return, but DD stays worse than the best proactive exit cells. |
| buy_stop_breakout | `buy_stop_005` (8.058% / 15.900% DD) | `buy_stop_005` (8.058% / 15.900% DD) | 0.5-1.0% for lower-DD entry experiments; 0.5% is the better return/DD balance. | medium | Buy-stop offsets reduce DD materially versus scratch baseline, with lower return. |
| flat_position_atr | `scratch_base` (5.996% / 18.300% DD) | `pos_03_atr_075` (5.616% / 13.700% DD) | 3% position with wider ATR if DD cap matters; avoid 5% flat sizing. | low | 3% position lowers DD sharply; 5% position increases DD without return improvement. |
| vol_adjusted_risk | `volrisk_125` (11.897% / 34.900% DD) | `volrisk_125` (11.897% / 34.900% DD) | Do not promote without hard gross/DD controls. | medium | Both vol-risk cells increase return by accepting too much drawdown. |
| resistance_or_breadth_gate | `scratch_base` (5.996% / 18.300% DD) | `scratch_base` (5.996% / 18.300% DD) | Treat as non-binding in this config path; instrument before retesting. | low | Both variants matched scratch_base exactly, so these params likely did not bind. |

## Entry Indicator Ranges

Decision-rank is lower-is-better liquidity/DV rank. These bins are trade-level observations across variants, so they are useful for pattern discovery but are not independent samples.

| indicator bucket | closed trades | win rate | avg return | median return | confidence |
| --- | ---: | ---: | ---: | ---: | --- |
| rank_000_024 | 9674 | 51.9% | 0.872% | 0.117% | high |
| rank_025_049 | 3369 | 47.9% | 0.711% | -0.063% | high |
| rank_050_099 | 5767 | 43.3% | 0.068% | -0.103% | high |
| rank_100_249 | 1883 | 52.1% | 0.480% | 0.075% | high |

| gap bucket | closed trades | win rate | avg return | median return | confidence |
| --- | ---: | ---: | ---: | ---: | --- |
| gap_lt_-1pct | 1811 | 45.1% | -0.378% | -0.259% | high |
| gap_-1_to_0pct | 7370 | 48.5% | 0.534% | -0.039% | high |
| gap_0_to_1pct | 8777 | 49.6% | 0.674% | -0.008% | high |
| gap_1_to_2pct | 2556 | 50.1% | 1.136% | 0.031% | high |
| gap_gt_2pct | 179 | 46.4% | 0.328% | -0.385% | medium |

| volatility bucket | closed trades | win rate | avg return | median return | confidence |
| --- | ---: | ---: | ---: | ---: | --- |
| (0.173, 4.061] | 5192 | 46.1% | 0.300% | -0.086% | high |
| (4.061, 5.508] | 5169 | 47.8% | 0.607% | -0.047% | high |
| (5.508, 7.194] | 5168 | 49.4% | 0.815% | -0.024% | high |
| (7.194, 16.814] | 5164 | 52.1% | 0.623% | 0.122% | high |

| hold bucket | closed trades | win rate | avg return | median return | confidence |
| --- | ---: | ---: | ---: | ---: | --- |
| hold_0_1d | 5570 | 44.0% | -0.317% | -0.119% | high |
| hold_1_3d | 3437 | 40.8% | -0.434% | -0.200% | high |
| hold_3_7d | 6524 | 48.7% | 0.001% | -0.038% | high |
| hold_7_14d | 2464 | 54.8% | 1.637% | 0.285% | high |
| hold_14_30d | 1853 | 64.2% | 3.984% | 1.984% | high |
| hold_30d_plus | 845 | 64.3% | 4.683% | 2.481% | high |

## Symbol Edges

These are repeated across variants, so use them as ticker-behavior clues, not independent production rankings.

| symbol | closed trades | win rate | avg return | median return | total pnl | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| AVGO | 1427 | 53.7% | 1.368% | 0.262% | 78257 | high |
| AMD | 1112 | 52.2% | 1.714% | 0.377% | 77824 | high |
| ORCL | 1218 | 45.3% | 1.464% | -0.528% | 69977 | high |
| GOOGL | 894 | 54.5% | 1.622% | 0.201% | 62668 | high |
| NVDA | 623 | 62.3% | 1.367% | 0.531% | 36693 | high |
| LLY | 582 | 52.2% | 1.405% | 0.197% | 32452 | high |
| TSLA | 496 | 54.0% | 1.543% | 0.346% | 30908 | medium |
| ABBV | 1122 | 56.9% | 0.566% | 0.153% | 27802 | high |

| weak symbol | closed trades | win rate | avg return | median return | total pnl | confidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| COST | 974 | 40.9% | 0.059% | -0.100% | 1965 | high |
| MRK | 972 | 51.1% | -0.008% | 0.039% | 1388 | high |
| CRM | 540 | 40.7% | 0.070% | -0.282% | 798 | high |
| V | 1738 | 39.9% | -0.016% | -0.088% | -3020 | high |
| HD | 980 | 38.5% | -0.131% | -0.318% | -7318 | high |
| NFLX | 1154 | 48.1% | -0.860% | -0.016% | -52373 | high |

## Confidence Notes

- High/medium/low on trade bins is sample-size confidence, not causal proof.
- Parameter confidence is capped at medium because this is one FY2025 slice and variants are correlated.
- `exit_events_all.csv` remains empty because current phase logs do not emit per-symbol exit events.
- Sector, industry, market regime, intraday candle path, George scanner context, and Falk scanner context still require enrichment before claiming George-reasoning replication.
