# Scanner Source Diagnostics

## Goal

Build issue #485: explain the synthesized #482 trade universe by source bucket so we can see
what George-only, Kumo-only, shared, and video-context opportunities contribute.

## Files

- `scripts/analyze_scanner_source_diagnostics.py`
  - Read `sweeps/reports/scanner_trade_universe_482/scanner_trade_universe.csv.gz`.
  - Produce source outcome distributions, reason-code summaries, date-level examples,
    missed optimal trades, high-risk false positives, report, and manifest.
- `tests/scripts/test_analyze_scanner_source_diagnostics.py`
  - Cover source metrics, reason-code explosion, missed-optimal classification, and daily examples.
- `sweeps/reports/scanner_source_diagnostics_485/README.md`
  - Document generated artifacts for #485.

## Outputs

- `source_outcome_summary.csv`
  - Counts and percentages by `source_bucket`.
  - Includes trigger rate, optimal/bad/watch share, average entry/exits, and model-score averages.
- `reason_code_summary.csv`
  - Exploded `reason_codes` by source bucket and trade bucket.
- `missed_optimal_trades.csv`
  - Optimal trades that one side did not surface: Kumo-only rows missed by George, George-only rows missed by Kumo,
    and Kumo+George-video-context rows missed by George scanner/watchlist.
- `high_risk_false_positives.csv`
  - Bad trades grouped by source bucket, sorted by MAE/deployable-exit damage.
- `daily_source_examples.csv`
  - Per-date examples for Kumo additions, George additions, shared winners, shared traps, and video-context rows.
- `scanner_source_diagnostics_report.md`
  - Compact interpretation and next-action notes.

## Verification

- `python3 -m pytest tests/scripts/test_analyze_scanner_source_diagnostics.py`
- `python3 scripts/analyze_scanner_source_diagnostics.py`

## Caveats

- This analysis inherits #482 labels. It does not retrain or relabel.
- George video-only context remains distinct from scanner/watchlist evidence.
