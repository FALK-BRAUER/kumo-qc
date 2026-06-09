# LambdaMART Scanner Experiment

Issue: #435

Purpose: test whether a grouped learning-to-rank model improves George top-list alignment after denominator ranks and profiled breadth.

## Protocol

- Label set: `george_oof_stage1_scores.csv`, 306 covered George rows.
- Denominator: `george_ranking_denominator_profiled.csv`.
- Base panel: top3000 ADV20 price>=10, BCT score>=6.
- Validation: chronological date-grouped OOF folds.
- Model: LightGBM `LGBMRanker` with `objective=lambdarank`.
- Features enabled by default: sector context, denominator ranks, profiled sector/industry breadth.
- Runtime status: research-only optional dependency. Local benchmark required `lightgbm`, `scikit-learn`, and macOS `libomp`.

## Result

| Variant | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pairwise + denominator ranks + breadth, clean_top2000 | 51 | 88 | 122 | 175 | 187 | 19.13% | 15.0 |
| LambdaMART + denominator ranks + breadth, clean_top2000 | 69 | 100 | 140 | 186 | 202 | 21.74% | 13.0 |
| LambdaMART + denominator ranks + breadth, score7_or_clean6 | 68 | 103 | 138 | 190 | 212 | 22.39% | 15.0 |
| LambdaMART + denominator ranks + breadth, all rows | 69 | 107 | 143 | 195 | 231 | 23.26% | 20.0 |

## Lift

Against #434 clean-top2000 pairwise baseline, LambdaMART clean-top2000 adds:

- `+18` hits@5
- `+12` hits@10
- `+18` hits@20
- `+11` hits@50
- `+15` hits@100

The all-rows LambdaMART variant is best at top10: `107/306`, with `23.26%` precision@10. That suggests the model can rank the broader score-6 lane directly instead of relying on the clean_top2000 gate.

## Read

This is the first model-class result that materially moves the top10 benchmark. It does not reach the user's desired 60-70% top10 recall, but it raises the current offline top10 selector from `72/306` before #431 to `107/306`.

The top importances still center on chart/return and denominator-rank context: `d_tenkan_extension_pct`, `day_return_pct`, `d_return_10d_pct`, `day_return_pct_rank_in_panel`, `day_return_pct_pctile_in_panel`, and `day_dollar_vol_pctile_in_panel`.

Next step is #433: positive-unlabeled weighting and two-stage reranking on this LambdaMART harness.
