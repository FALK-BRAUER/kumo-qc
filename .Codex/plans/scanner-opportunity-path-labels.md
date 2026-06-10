# Scanner Opportunity Path Labels

## Goal

Implement issue #464 by replaying future paths for the #463 scanner opportunity panel. This
phase consumes the label-free panel and adds future outcome labels in a separate artifact.

## Data Source

- Input panel:
  `sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Raw path source:
  `/Users/falk/projects/kumo-trader/data/intraday/YYYY-MM-DD.parquet`

The script will compute regular-session daily bars from parquet and avoid QC Cloud.

## First Entry Assumption

- `next_regular_open`: enter at the next available market session open after `scan_date`.

Additional entry triggers belong to #465 after this label surface is stable.

## Labels

For horizons 1, 2, 5, 10, 20, and 40 trading sessions from entry:

- close return from entry open
- MFE from entry open using daily highs
- MAE from entry open using daily lows
- target-before-stop / stop-before-target / ambiguous / neither for 4% target / -2% stop
- target-before-stop / stop-before-target / ambiguous / neither for 8% target / -4% stop
- time to peak in sessions
- max giveback after peak

Also add compact outcome labels: `runner_candidate`, `normal_winner`, `bad_trade`,
`chop_or_unclear`, and path coverage status.

## Files

- `scripts/build_scanner_opportunity_path_labels.py`
- `tests/scripts/test_build_scanner_opportunity_path_labels.py`
- `sweeps/reports/scanner_opportunity_paths_464/`
  - `README.md`
  - `opportunity_path_labels.csv.gz`
  - `source_outcome_summary.csv`
  - `coverage_summary.csv`
  - `best_opportunities.csv`
  - `worst_opportunities.csv`
  - `manifest.json`
  - `opportunity_path_report.md`

## Verification

- Focused path-label pytest.
- Full script run against the #463 panel and local parquet.
- `git diff --check`.
