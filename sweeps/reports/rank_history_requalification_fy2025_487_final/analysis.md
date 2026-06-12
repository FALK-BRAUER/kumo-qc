# #487 FY2025 Rank-History Requalification Analysis

## Executive Read

- The rank-history layer is implemented and opt-in, and the current champion remains unchanged.
- Dynamic score-medium controls still starve participation: orders fell roughly 41-52% versus scanner-off controls.
- Rank-history `core50` restores participation, but the retry funnel shows why: the daily signal panel averages about 23 names, so `core_rank=50` is effectively pass-through after repeat appearances.
- The cleanest non-sizing rows are small improvements for `giveback_no_bull` and `target04_fast_take`; `target08_let_run` does not improve.
- Rank-aware sizing creates the biggest realized PnL, but drawdown rises to about 21%, so it is not promotion-ready.
- Recommendation: keep the runtime rank-history layer, reject `core50` as a final gate, and iterate on narrower requalification or full-scanner/universe rank memory before any champion switch.

## Base Comparisons

| base | row | ret_pct | dd_pct | orders | order_delta_vs_off | realized | unrealized | closed_trades | win_rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| giveback_no_bull | rh_off | 10.227 | 17.5 | 341 | +0.0% | 23594.96 | -13050.23 | 159 | 83.6 |
| giveback_no_bull | rh_dynamic_score_medium | 7.005 | 9.0 | 165 | -51.6% | 11237.55 | -4074.16 | 79 | 88.6 |
| giveback_no_bull | rh_requal_core50 | 10.321 | 17.3 | 301 | -11.7% | 24191.16 | -13592.17 | 139 | 96.4 |
| giveback_no_bull | rh_requal_entry | 9.830 | 17.5 | 315 | -7.6% | 23733.92 | -13612.15 | 146 | 92.5 |
| giveback_no_bull | rh_requal_sizing | 17.908 | 21.0 | 265 | -22.3% | 31848.02 | -13696.16 | 122 | 94.3 |
| giveback_no_bull | rh_requal_entry_sizing | 13.135 | 20.0 | 270 | -20.8% | 29034.01 | -15651.38 | 124 | 87.9 |
| target04_fast_take | rh_off | 9.305 | 17.6 | 275 | +0.0% | 23660.67 | -14103.40 | 126 | 97.6 |
| target04_fast_take | rh_dynamic_score_medium | 8.539 | 10.5 | 155 | -43.6% | 13554.68 | -4869.82 | 73 | 97.3 |
| target04_fast_take | rh_requal_core50 | 9.631 | 17.5 | 263 | -4.4% | 23804.23 | -13932.87 | 120 | 98.3 |
| target04_fast_take | rh_requal_entry | 8.428 | 17.2 | 263 | -4.4% | 22549.78 | -13882.23 | 120 | 99.2 |
| target04_fast_take | rh_requal_sizing | 16.428 | 21.3 | 221 | -19.6% | 30978.23 | -14351.89 | 99 | 100.0 |
| target04_fast_take | rh_requal_entry_sizing | 13.124 | 21.3 | 225 | -18.2% | 29511.62 | -16183.15 | 102 | 98.0 |
| target08_let_run | rh_off | 10.495 | 17.5 | 257 | +0.0% | 24177.30 | -13448.48 | 117 | 91.5 |
| target08_let_run | rh_dynamic_score_medium | 9.661 | 14.9 | 152 | -40.9% | 14969.33 | -5168.08 | 70 | 97.1 |
| target08_let_run | rh_requal_core50 | 8.837 | 17.4 | 255 | -0.8% | 22217.15 | -13147.66 | 116 | 88.8 |
| target08_let_run | rh_requal_entry | 9.985 | 17.3 | 233 | -9.3% | 23332.27 | -13137.70 | 105 | 94.3 |
| target08_let_run | rh_requal_sizing | 11.943 | 21.0 | 180 | -30.0% | 27940.66 | -15839.87 | 79 | 94.9 |
| target08_let_run | rh_requal_entry_sizing | 10.317 | 22.1 | 169 | -34.2% | 23936.02 | -13469.05 | 75 | 94.7 |

## Funnel Read

- Existing engine funnel counters are present in FY result JSON for completed rows.
- Scanner funnel counters are verified on the successful retry row built with the final code.
- Retry scanner funnel: days=250, raw=5750, ranked=5750, rank_history_eligible=5737, selected=5737, top20_seen_last_20=4977.
- Interpretation: rank persistence is extremely high, but `core_rank=50` is too wide for the post-signal panel and therefore almost all repeated names requalify.

## Decision

- Promote the opt-in rank-history infrastructure to PR review as experimental plumbing.
- Do not promote `core50`, rank-aware entry, or rank-aware sizing to production champion.
- Next experiment should either rank a broader scanner/universe panel before signal collapse or test narrower states such as current top10 plus repeated top20/top30 with explicit per-state diagnostics.
