# Scanner Opportunity Ranker Plan

## Goal

Complete issue #467 by training leakage-safe, date-grouped opportunity rankers from the #464
future-path labels. The model must use only scan-time features and produce out-of-fold predictions
that can be compared against the current Kumo rank and simple rule baselines.

## Files

- `scripts/train_scanner_opportunity_ranker.py`
  - Read #464 labels and #463 scan-time metadata.
  - Build scan-time features only; exclude George/source labels and future path labels from features.
  - Train expanding-window date-grouped pairwise rankers for trade-worthy and runner labels.
  - Save out-of-fold predictions, top-K metrics, monthly stability, coefficient diagnostics, and
    a final linear-model JSON artifact under `sweeps/reports/scanner_opportunity_ranker_467/`.

- `tests/scripts/test_train_scanner_opportunity_ranker.py`
  - Verify feature leakage guard.
  - Verify walk-forward folds train strictly before validation dates.
  - Verify top-K metric math on a small synthetic panel.

- `sweeps/reports/scanner_opportunity_ranker_467/`
  - Generated compact research output for issue #467.

## Verification

- Run focused pytest for the new harness.
- Run ruff on script/test.
- Run the full report on the default `kumo_top100_or_george` subset.
- Confirm OOF metrics compare model scores against scanner-rank and rule baselines.
