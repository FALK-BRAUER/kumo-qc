# Scanner Runtime Promotion Gate

Issue: #432

Purpose: prevent scanner-alignment research lift from leaking into QC runtime when the feature source is
lab-only, George-derived, or not reproducible in QuantConnect cloud.

## Promotion Criteria

A scanner feature or model can move from `research/scanner-alignment/` into runtime only when all criteria
are true:

1. The experiment is logged in `experiment_log.csv` with `status=complete`, a commit, a source report, and
   a reproducible command.
2. The feature set shows date-grouped out-of-fold lift on George top-list recall, with the target metric
   named before the experiment. For this backlog, the target metric is recall@10 over the 306 covered labels.
3. Every runtime input column is classified in `feature_parity_columns.csv`.
4. Every runtime input column has `safe_for_qc_handoff=True` and
   `deployability_class=qc_cloud_deployable`, or the PR explicitly limits the feature to local research.
5. The implementation adds runtime tests for local data availability and cloud-package compatibility.
6. No George/OCR/community-post/video-derived evidence, offline OOF score, in-sample model score, or lab-only
   denominator rank is used by the live scanner.

## Feature Availability

The explicit feature-level allow/deny list is `feature_parity_columns.csv`. The gate validator is
`scripts/validate_scanner_promotion_gate.py`.

### QC Cloud-Ready

Allowed for runtime promotion after normal tests:

- `safe_for_qc_handoff=True`
- `deployability_class=qc_cloud_deployable`
- `qc_status` is `qc_ranker_feature` or `clean_available_not_used`

Examples: `gap_pct`, `day_return_pct`, `rel_volume20`, `daily_structure_score`,
`d_tenkan_extension_pct`, `d_cloud_distance_pct`, `d_return_10d_pct`, `d_body_pct_range`.

### QC Local-Only

Allowed for local Massive simulation only; denied for QC cloud until the same live denominator can be
reproduced in cloud:

- `deployability_class=local_massive_only`
- `safe_for_qc_handoff=False`

Examples: `adv20_rank_price10`, `day_dv_rank_price10`, `gap_pct_rank_in_panel`,
`day_return_pct_rank_in_panel`, `daily_structure_score_rank_in_panel`,
`daily_cloud_distance_pct_rank_in_panel`.

### TC2000 Mapping Required

Allowed for research only until a TC2000-compatible sector and industry mapping exists in both local and cloud:

- `deployability_class=tc2000_mapping_required`
- `safe_for_qc_handoff=False`

Examples: `sector_bct7_pct`, `sector_positive_return_count`, `industry_bct6_count`,
`industry_median_rel_volume20`.

### Denied

Never allowed as live scanner inputs:

- George-derived labels or provenance: `george_included`, `scanner_rank`, `decision_label`,
  `candidate_source`, `ocr_text_path`, `post_id`, `source_path`.
- Offline model scores: OOF scores, in-sample scores, `base_model_score`, and `scanner_time_*` scores.
- Any feature whose value is computed using George's output list for that same label row.

These features can remain in research reports as labels, diagnostics, or leakage checks.

## Current Decision

After #431, #434, #435, #433, #423 clean-subset testing, and the feature-source ablation, there is no
runtime scanner promotion yet.

- #431 denominator ranks improved clean_top2000 recall@10 from `72/306` to `87/306`, but those ranks are
  local denominator-relative and need a live QC denominator before cloud promotion.
- #434 sector/industry breadth produced only a small pairwise lift and is blocked on TC2000-compatible
  sector and industry mapping.
- #435 plain LambdaMART is the current best research selector at `107/306` recall@10 on the broad score-6
  panel, but it is an optional research harness and uses features that are not all cloud-ready.
- #433 PU weighting and two-stage reranking did not beat #435, so it is not a runtime candidate.
- #423 QC-cloud-safe feature filtering dropped LambdaMART clean_top2000 recall@10 to `88/306` and all-rows
  recall@10 to `72/306`, below the promotion threshold.
- The #423 feature-source ablation showed sector/industry breadth is the best clean_top2000 lift
  (`88/306` to `101/306` recall@10), while denominator-relative ranks are the best broad-pool lift
  (`72/306` to `100/306` all-row recall@10). Both remain blocked for cloud promotion.

The next promotable path is #442: build a QC-cloud-reproducible sector/industry breadth substrate, then
rerun the clean_top2000 LambdaMART subset against that deployable feature source. Denominator-relative ranks
remain the second path once a matching live candidate-panel denominator exists in cloud.
