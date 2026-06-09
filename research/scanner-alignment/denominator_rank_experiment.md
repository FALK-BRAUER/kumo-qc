# Denominator-Rank Scanner Experiment

Issue: #431

Purpose: test whether George-style top-list alignment needs per-date candidate-panel context, not only absolute chart values.

## Protocol

- Label set: `george_oof_stage1_scores.csv`, 306 covered George rows.
- Denominator: `george_ranking_denominator_profiled.csv`.
- Base panel: top3000 ADV20 price>=10, BCT score>=6.
- Validation: chronological date-grouped OOF folds.
- Model: dependency-free pairwise linear ranker.
- Runtime status: research-only. The rank features are recomputed from raw candidate-panel columns; they do not read George rank, OCR rows, transcripts, or lab model scores.

## Features Added

For each date, the harness computes rank and percentile features over the live score-6 candidate panel:

- `gap_pct`
- `day_return_pct`
- `rel_volume20`
- `d_rel_volume50`
- `bct_score`
- `daily_structure_score`
- `d_cloud_distance_pct`
- `daily_breakout_quality_score`
- `day_dollar_vol`
- `adv20_incl_today`

## Result

| Variant | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pairwise + sector, clean_top2000 | 46 | 72 | 109 | 160 | 187 | 15.65% | 19.0 |
| pairwise + sector + denominator ranks, clean_top2000 | 49 | 87 | 121 | 173 | 191 | 18.91% | 14.5 |
| delta | +3 | +15 | +12 | +13 | +4 | +3.26 pp | -4.5 |

The broader gates also improved:

| Variant | hits@10 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: |
| pairwise + sector, score7_or_clean6 | 62 | 155 | 195 | 13.48% | 24.0 |
| pairwise + sector + denominator ranks, score7_or_clean6 | 77 | 175 | 198 | 16.74% | 22.0 |
| pairwise + sector, all rows | 59 | 161 | 205 | 12.83% | 34.0 |
| pairwise + sector + denominator ranks, all rows | 75 | 176 | 214 | 16.30% | 30.0 |

## Read

Denominator context is real signal. It moved the clean top10 benchmark from 72/306 to 87/306 without a new model class.

The largest new coefficients include `day_return_pct_rank_in_panel`, `day_return_pct_pctile_in_panel`, `day_dollar_vol_pctile_in_panel`, `gap_pct_pctile_in_panel`, and `adv20_pctile_in_panel`, which matches the #430 feature-parity diagnosis.

This is still not a cloud promotion. The next research step is #434: TC2000-style sector and industry breadth on top of these denominator ranks.
