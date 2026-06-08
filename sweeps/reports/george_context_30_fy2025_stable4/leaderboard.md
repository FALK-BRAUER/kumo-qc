# George Context 30-Pack FY2025 Stable4

Combined report for the five FY2025 George-context sweep waves, each run with valid final LEAN statistics and stable four-container effective concurrency.

## Top Variants

| Rank | Variant | Family | Return % | DD % | Orders | Sharpe |
|---:|---|---|---:|---:|---:|---:|
| 1 | entry_gapvol_base | entry_confirmation | 27.813 | 20.2 | 74 | 0.984 |
| 2 | entry_gapvol_vol125 | entry_confirmation | 27.813 | 20.2 | 74 | 0.984 |
| 3 | entry_gapvol_vol150 | entry_confirmation | 27.813 | 20.2 | 74 | 0.984 |
| 4 | exit_kijun_phase3_base | exit_management | 27.813 | 20.2 | 74 | 0.984 |
| 5 | exit_cloud_adherence | exit_management | 27.813 | 20.2 | 74 | 0.984 |
| 6 | exit_weekly_kijun | exit_management | 27.813 | 20.2 | 74 | 0.984 |
| 7 | exit_proactive_target_06 | exit_management | 27.813 | 20.2 | 74 | 0.984 |
| 8 | exit_proactive_giveback_tight | exit_management | 27.813 | 20.2 | 74 | 0.984 |
| 9 | exit_scratch_flat_3d | exit_management | 27.813 | 20.2 | 74 | 0.984 |
| 10 | industry_top3_focus | industry_warmup | 27.695 | 19.4 | 72 | 1.025 |
| 11 | industry_top8_broad | industry_warmup | 27.695 | 19.4 | 72 | 1.025 |
| 12 | industry_bct_share_heavy | industry_warmup | 27.695 | 19.4 | 72 | 1.025 |

## Family Summary

| Family | N | Best Variant | Best Return % | Best DD % | Avg Return % | Worst Variant | Worst Return % |
|---|---:|---|---:|---:|---:|---|---:|
| entry_confirmation | 6 | entry_gapvol_base | 27.813 | 20.2 | 19.010 | entry_gapvol_gap05 | 0.018 |
| exit_management | 6 | exit_kijun_phase3_base | 27.813 | 20.2 | 27.813 | exit_kijun_phase3_base | 27.813 |
| george_attention | 6 | attention_ticker_heavy | 27.197 | 20.2 | 25.802 | attention_floor_05 | 22.241 |
| industry_warmup | 6 | industry_top3_focus | 27.695 | 19.4 | 27.470 | industry_attention_boost | 26.343 |
| watchlist_carry | 6 | carry_3_ttl5 | 27.695 | 19.4 | 27.695 | carry_3_ttl5 | 27.695 |

## Readout

- Best return group is 27.813% with 20.2% DD and 74 orders: intraday gap-vol base, volume threshold variants, and all tested exit-management variants.
- Baseline-like industry/carry variants are 27.695% with lower 19.4% DD and 72 orders, so they have better Sharpe in this pack despite slightly lower return.
- George attention variants mostly reduce return and increase DD; the `attention_floor_05` setting is the weakest attention run at 22.241%.
- Stricter entry gap/window settings are clear rejects: gap05 is nearly flat at 0.018%, gap04 is 11.952%, and window60 is 18.652%.
- Exit variations are behaviorally inert in this sweep: every tested exit variant equals the intraday gap-vol base result.
