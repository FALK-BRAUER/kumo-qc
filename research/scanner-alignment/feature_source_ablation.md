# Feature-Source Ablation

Issue: #423

Purpose: identify which blocked or non-runtime feature source explains the gap between the QC-cloud-safe
LambdaMART subset and the full research LambdaMART scanner selector.

## Protocol

- Label set: `george_oof_stage1_scores.csv`, 306 covered George rows.
- Denominator: `george_ranking_denominator_profiled.csv`.
- Base panel: top3000 ADV20 price>=10, BCT score>=6.
- Validation: chronological date-grouped OOF folds.
- Model: LightGBM LambdaMART, same hyperparameters as #435 and #441.
- Baseline feature set: raw QC-cloud-safe chart features from `feature_parity_columns.csv`.
- Added sources:
  - denominator-relative ranks;
  - profiled sector/industry context;
  - profiled sector/industry breadth;
  - full current research feature set as a reference.

## Clean Top2000 Result

| Cell | Feature count | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | MAP seen | NDCG@10 seen | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw + sector breadth | 78 | 64 | 101 | 139 | 189 | 208 | 21.96% | 35.98% | 43.43% | 13.0 |
| full research reference | 149 | 69 | 100 | 140 | 186 | 202 | 21.74% | 37.44% | 44.47% | 13.0 |
| raw + denominator ranks + sector context | 121 | 66 | 99 | 136 | 183 | 200 | 21.52% | 39.37% | 46.02% | 13.0 |
| raw + sector context | 101 | 63 | 96 | 140 | 191 | 208 | 20.87% | 38.56% | 44.42% | 12.5 |
| raw + denominator ranks + sector breadth | 98 | 68 | 95 | 143 | 177 | 198 | 20.65% | 39.21% | 44.71% | 13.0 |
| raw + denominator ranks | 80 | 62 | 94 | 140 | 181 | 199 | 20.43% | 37.30% | 43.33% | 12.0 |
| raw QC-safe | 60 | 52 | 88 | 133 | 183 | 204 | 19.13% | 31.69% | 37.46% | 15.0 |

## All-Rows Result

| Cell | Feature count | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | MAP seen | NDCG@10 seen | median George rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full research reference | 149 | 69 | 107 | 143 | 195 | 231 | 23.26% | 29.80% | 37.65% | 20.0 |
| raw + denominator ranks + sector breadth | 98 | 71 | 102 | 138 | 190 | 225 | 22.17% | 31.80% | 38.59% | 21.0 |
| raw + denominator ranks + sector context | 121 | 70 | 102 | 142 | 196 | 228 | 22.17% | 31.46% | 38.67% | 20.0 |
| raw + denominator ranks | 80 | 66 | 100 | 148 | 193 | 229 | 21.74% | 30.15% | 36.67% | 19.0 |
| raw + sector breadth | 78 | 63 | 96 | 134 | 190 | 226 | 20.87% | 28.91% | 36.51% | 22.0 |
| raw + sector context | 101 | 61 | 96 | 134 | 190 | 234 | 20.87% | 30.68% | 37.16% | 23.0 |
| raw QC-safe | 60 | 47 | 72 | 117 | 178 | 223 | 15.65% | 23.49% | 27.57% | 29.0 |

## Read

The gap is not mostly model class anymore. It is feature-source availability.

- Clean top2000 ranking is most helped by sector/industry breadth: `88/306 -> 101/306` recall@10.
- Broad all-row ranking is most helped by denominator-relative ranks: `72/306 -> 100/306` recall@10.
- Full research all-row remains best at `107/306`, but still below the `117/306` promotion target.
- None of the cells is promotable to runtime because the winning sources are not QC-cloud-deployable yet.

The highest-importance sector-breadth features in the best clean cell are:

- `sector_median_rel_volume20`
- `industry_median_rel_volume20`
- `industry_positive_return_pct`
- `industry_median_day_return_pct`

The best clean cell still misses George rows such as:

| Date | George row rank | Top10 selected instead |
| --- | ---: | --- |
| 2026-04-30 | `TSEM@142` | MKSI, CGNX, CIEN, QSR, DLR, GLW, ALSN, EGP, RY, AEIS |
| 2026-03-25 | `PFE@51` | MRNA, DRS, CASY, FHI, UTHR, ERIC, SEB, CGON, RPRX, BG |
| 2026-03-16 | `AHR@39` | PWR, CRC, ECG, CW, MSGS, AA, LHX, UI, VRT, MTZ |
| 2026-03-30 | `PFE@27` | QSR, UTHR, FE, DUK, ACLX, EXC, SRE, HGER, SHEL, ATO |

## Decision

Prioritize #442 / #409-style sector/industry mapping before trying more model variants. The best next
runtime-facing work is a TC2000-compatible sector/industry breadth substrate that can be computed locally and
in QC cloud.

In parallel, denominator-relative ranks remain useful for broad-pool selection, but they require a live
candidate-panel denominator in cloud before promotion.
