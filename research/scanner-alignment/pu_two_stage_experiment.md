# PU And Two-Stage Scanner Experiment

Issue: #433

Purpose: test whether weak-negative weighting and stage1-topN/stage2 reranking improve the #435 LambdaMART selector.

## Protocol

- Label set: `george_oof_stage1_scores.csv`, 306 covered George rows.
- Denominator: `george_ranking_denominator_profiled.csv`.
- Base panel: top3000 ADV20 price>=10, BCT score>=6.
- Validation: chronological date-grouped OOF folds.
- Model: optional LightGBM LambdaMART harness from #435.
- Features enabled: sector context, denominator ranks, profiled sector/industry breadth.

## Result

All-rows score-6 panel:

| Variant | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| #435 LambdaMART baseline | 69 | 107 | 143 | 195 | 231 | 23.26% | 20.0 |
| PU weak negatives, negative_weight=0.25 | 64 | 100 | 144 | 193 | 226 | 21.74% | 20.0 |
| two-stage top100 | 66 | 99 | 145 | 198 | 231 | 21.52% | 20.0 |
| PU weak negatives + two-stage top100 | 57 | 90 | 135 | 189 | 226 | 19.57% | 21.0 |

Clean-top2000 gate:

| Variant | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| #435 LambdaMART baseline | 69 | 100 | 140 | 186 | 202 | 21.74% | 13.0 |
| PU weak negatives, negative_weight=0.25 | 63 | 97 | 137 | 185 | 203 | 21.09% | 13.0 |
| two-stage top100 | 68 | 99 | 140 | 187 | 196 | 21.52% | 12.0 |
| PU weak negatives + two-stage top100 | 57 | 93 | 134 | 184 | 195 | 20.22% | 13.5 |

## Read

This does not beat #435. Positive-unlabeled weighting reduced top10 recall, and two-stage top100 did not improve the all-rows selector. The current best remains plain LambdaMART over the broad score-6 panel.

The likely explanation is that the grouped ranking objective already handles many weak negatives through relative ordering, while the simple PU weights remove useful contrast. The two-stage path may still be useful later with a better stage1 objective or a larger topN, but it should not be promoted now.
