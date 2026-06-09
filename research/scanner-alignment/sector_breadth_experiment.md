# Sector-Breadth Scanner Experiment

Issue: #434

Purpose: test whether profiled sector and industry breadth facts add George-style top-down context after the #431 denominator-rank lift.

## Protocol

- Label set: `george_oof_stage1_scores.csv`, 306 covered George rows.
- Denominator: `george_ranking_denominator_profiled.csv`.
- Base panel: top3000 ADV20 price>=10, BCT score>=6.
- Validation: chronological date-grouped OOF folds.
- Model: dependency-free pairwise linear ranker.
- Baseline: pairwise + sector context + denominator ranks from #431.
- Runtime status: research-only. The breadth columns depend on profiled sector/industry mappings and need #432 runtime handoff before cloud use.

## Features Added

The optional `--use-sector-breadth` flag adds raw profiled breadth columns:

- sector and industry denominator counts
- BCT score>=6 counts and percentages
- BCT score>=7 counts and percentages
- positive-return counts and percentages
- median day return
- median relative volume

## Result

| Variant | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pairwise + sector + denominator ranks, clean_top2000 | 49 | 87 | 121 | 173 | 191 | 18.91% | 14.5 |
| + profiled sector/industry breadth, clean_top2000 | 51 | 88 | 122 | 175 | 187 | 19.13% | 15.0 |
| delta | +2 | +1 | +1 | +2 | -4 | +0.22 pp | +0.5 |

The broader score7/clean6 gate moved more:

| Variant | hits@10 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: |
| pairwise + sector + denominator ranks, score7_or_clean6 | 77 | 175 | 198 | 16.74% | 22.0 |
| + profiled sector/industry breadth, score7_or_clean6 | 82 | 175 | 200 | 17.83% | 21.5 |

## Read

Sector/industry breadth is useful but not the next big lever in the current linear ranker. It adds a small clean top10 lift and a clearer broader-gate lift, but it does not change the main conclusion from #431: denominator-relative rank context carries the larger improvement.

The next high-upside step is #435, a grouped learning-to-rank model, using denominator ranks and breadth as inputs.
