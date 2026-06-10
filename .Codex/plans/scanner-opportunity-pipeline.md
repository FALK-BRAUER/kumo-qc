# Scanner Opportunity Pipeline

## Goal

Complete the scanner-opportunity research pipeline from issues #463-#468 without learning from
the sparse champion trades. The pipeline starts from the full candidate surface, labels future
paths only after the opportunity panel is built, then evaluates entry rules, exit policies, and
walk-forward ranking.

## Phase 1: #463 Opportunity Panel

Files to add or modify:

- `scripts/build_scanner_opportunity_panel.py`
  - Read George candidate evidence from
    `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_scanner_candidates_raw.csv`.
  - Read Kumo/Falk candidates from
    `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/falk_scanner_candidates_enriched.csv`.
  - Normalize to one canonical `scan_date + symbol` opportunity row.
  - Preserve source/provenance flags:
    `kumo_scanner`, `kumo_top_n`, `george_scanner_ocr`, `george_watchlist`,
    `george_video_mention`.
  - Preserve rank/score fields when present, but do not add future outcomes.
  - Deduplicate by `scan_date + symbol` while retaining source flags and provenance strings.
  - Write compact reports under `sweeps/reports/scanner_opportunity_panel_463/`.

- `tests/scripts/test_build_scanner_opportunity_panel.py`
  - Cover source-role classification.
  - Cover Kumo rank/top-N handling.
  - Cover date-symbol deduplication with merged provenance.
  - Cover that video-only rows are context evidence, not scanner positives.

- `scripts/README.md`
  - Document the new panel builder.

- `sweeps/reports/scanner_opportunity_panel_463/`
  - `README.md` documenting artifact purpose and source semantics.
  - `opportunity_panel.csv.gz` with the slim canonical panel.
  - `source_summary.csv`, `date_summary.csv`, and `manifest.json`.
  - `opportunity_panel_report.md` with counts, date range, source breakdown, and caveats.

Verification:

- Run the focused pytest file.
- Run the builder against local inputs.
- Run `git diff --check`.
- Confirm no future-path labels are present in the panel.

## Phase 2: #464 Future-Path Labels

Consume `opportunity_panel.csv.gz` and price data to compute MFE, MAE, forward returns,
target-before-stop, stop-before-target, time-to-peak, and max giveback. Keep labels separate
from scan-time features.

## Phase 3: #465 Entry Trigger Research

Compare realistic entry assumptions: next open, first-hour confirmation, breakout, pullback,
and invalidation/no-entry. Report good and bad scanner candidates by source/rank bucket.

## Phase 4: #466 Exit Realization Research

Evaluate fixed targets, partial take plus trail, giveback stops, cloud/swing-low trail,
time stops, and invalidation stops on the labeled opportunity paths.

## Phase 5: #467 Ranking

Train only after labels are validated. Use date-grouped walk-forward validation and compare
simple rule baselines before ML.

## Phase 6: #468 LEAN/QC Integration

Integrate the best simple policy/ranker into local LEAN Docker sweeps first. Document cache
keys, artifact loading, fallback behavior, and QC Cloud constraints before cloud runs.
