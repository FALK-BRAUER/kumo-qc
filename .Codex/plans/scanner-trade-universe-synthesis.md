# Scanner Trade Universe Synthesis

## Goal

Build issue #482: an explicit George/Kumo scanner trade-universe artifact that joins scanner
source flags, realistic entry replay labels, exit-policy outcomes, and opportunity-ranker scores.

## Files

- `scripts/build_scanner_trade_universe.py`
  - Add a reproducible builder for `scanner_trade_universe.csv.gz`, `optimal_trades.csv`,
    `bad_trades.csv`, summary tables, report, and manifest.
  - Keep classification and best-entry/best-exit logic in pure helper functions.
- `tests/scripts/test_build_scanner_trade_universe.py`
  - Cover best-entry selection, best-exit selection, optimal/bad classification, and source
    summary aggregation with synthetic data.
- `sweeps/reports/scanner_trade_universe_482/README.md`
  - Document generated artifact purpose and what belongs in the directory.

## Inputs

- `sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- `sweeps/reports/scanner_entry_replay_465/alternate_entry_labels.csv.gz`
- `sweeps/reports/scanner_exit_policies_466/exit_policy_labels.csv.gz`
- `sweeps/reports/scanner_opportunity_ranker_467/oof_predictions.csv.gz`

## Output Semantics

- One row per `scan_date|symbol` opportunity.
- Source flags are preserved and rolled into source buckets:
  `george_scanner_or_watchlist`, `george_video_only_context`, `kumo_top_n`, `kumo_scanner`,
  `both_george_and_kumo`, and `kumo_only`/`george_only`.
- Best realistic entry is selected from triggered entry assumptions using 20-session close return,
  then MFE, then lower MAE as tie-breakers.
- Best deployable exit is selected from `lean_and_qc_ready` policy rows by total 40-session equity
  return. Oracle best exit includes all policies and is marked separately.
- `trade_bucket` is `optimal`, `bad`, or `watch`; reason codes explain the bucket.

## Verification

- Run `pytest tests/scripts/test_build_scanner_trade_universe.py`.
- Run the builder once against existing local artifacts.
- Inspect output row counts and report caveats, especially that #466 exit-policy labels currently
  use next-open entry paths rather than all #465 alternate entry assumptions.
