# Scanner Feature-Parity Audit

Purpose: separate real QC-deployable scanner features from lab-only or George-derived lift before tuning another ranker.

## Inputs

- denominator: `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv`
- deployability inventory: `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_top10_feature_deployability_inventory.csv`
- lab feature-rich importances: `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_top10_feature_rich_importances.csv`
- lab feature-rich variants: `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_top10_feature_rich_variant_summary.csv`

## Summary

- denominator columns: 217
- current QC learned-ranker matrix features: 126
- lab feature-rich date-grouped CV: 44.7% recall@10, 28.36% precision@10
- lab stage-1 baseline: 31.81% recall@10, 20.18% precision@10
- top-25 lab importance statuses: {'blocked_local_massive_only': 7, 'blocked_tc2000_mapping': 2, 'clean_available_not_used': 3, 'non_deployable_model_score': 3, 'qc_ranker_feature': 9, 'unclassified_or_unused': 1}

## Denominator Column Status Counts

| qc_status | count |
| --- | --- |
| blocked_local_massive_only | 25 |
| blocked_tc2000_mapping | 16 |
| clean_available_not_used | 38 |
| non_deployable_george_evidence | 22 |
| qc_ranker_feature | 72 |
| unclassified_or_unused | 44 |

## Top Lab Importances That Are Not Clean QC Runtime Features

| feature | importance | qc_status | deployability_class |
| --- | --- | --- | --- |
| scanner_time_kijun_support_score | 0.22985614489070297 | non_deployable_model_score |  |
| scanner_time_touch_combined_score | 0.1353001508723213 | non_deployable_model_score |  |
| base_model_score | 0.0571948653350954 | non_deployable_model_score |  |
| daily_structure_score_rank_in_panel | 0.040956674892644984 | blocked_local_massive_only | local_massive_only |
| day_return_pct_rank_in_panel | 0.02949507134534879 | blocked_local_massive_only | local_massive_only |
| is_common_equity_proxy | 0.019261807807988435 | blocked_local_massive_only | local_massive_only |
| daily_cloud_distance_pct_rank_in_panel | 0.018375884789766483 | blocked_local_massive_only | local_massive_only |
| sector_positive_return_count | 0.01472147775980944 | blocked_tc2000_mapping | tc2000_mapping_required |
| day_return_rank_price10 | 0.0074826856451616726 | blocked_local_massive_only | local_massive_only |
| rel_volume50_rank_in_panel | 0.006375796683339097 | blocked_local_massive_only | local_massive_only |
| sector_bct7_pct | 0.006153727681216137 | blocked_tc2000_mapping | tc2000_mapping_required |
| gap_pct_rank_in_panel | 0.006068248471085187 | blocked_local_massive_only | local_massive_only |

## Clean Deployable Columns Not Yet In The QC Ranker Matrix

| feature | deployability_class | handoff_note |
| --- | --- | --- |
| open | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| high | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| low | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| close | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| volume | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| day_dollar_vol | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| adv20_incl_today | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_price_inside_cloud | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_price_below_cloud | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_magnet_pattern | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_resistance_rejection_today | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_volume_ma50 | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_rel_volume50 | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_kijun_overhead_pct | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_ma200_overhead_pct | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_kijun_overhead_within3 | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_ma200_overhead_within3 | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_tenkan | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_kijun | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |
| d_cloud_top | qc_cloud_deployable | safe to hand to kumo-qc after normal QC data-availability checks |

## Blocked Local Or TC2000-Dependent Columns

| feature | qc_status | deployability_class | handoff_note |
| --- | --- | --- | --- |
| avg_volume20 | blocked_local_massive_only | local_massive_only | review before QC handoff |
| gap_rank_price10 | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| day_return_rank_price10 | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| rel_volume20_rank_price10 | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| history_days_for_adv | blocked_local_massive_only | local_massive_only | review before QC handoff |
| price_floor | blocked_local_massive_only | local_massive_only | review before QC handoff |
| adv20_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| day_dollar_vol_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| gap_pct_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| day_return_pct_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| rel_volume20_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| daily_structure_score_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| bct_score_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| daily_cloud_distance_pct_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| daily_breakout_quality_score_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| rel_volume50_rank_in_panel | blocked_local_massive_only | local_massive_only | port only after matching the live QC universe and rank denominator |
| profile_active | blocked_local_massive_only | local_massive_only | review before QC handoff |
| is_known_product_symbol | blocked_local_massive_only | local_massive_only | review before QC handoff |
| is_etf_category | blocked_local_massive_only | local_massive_only | review before QC handoff |
| is_arca_listed | blocked_local_massive_only | local_massive_only | review before QC handoff |

## Read

- The QC ranker already consumes the main clean daily/weekly structure family.
- More clean QC columns alone are unlikely to explain the lab lift; the lab feature-rich top importances include offline OOF model scores and local/panel-relative ranks.
- The next deployable gap is not another blind model class. It is TC2000-compatible sector/industry breadth plus a clean way to reproduce live denominator-relative ranks.
