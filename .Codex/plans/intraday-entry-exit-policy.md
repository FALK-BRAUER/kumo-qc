# Intraday Entry/Exit Policy #490

## Goal

Train first-pass as-of-safe policy models from the #491 intraday decision panel.
The model receives a ranked scanner candidate and the current intraday state; it predicts
entry actions separately from position-management actions.

## Inputs

- `sweeps/reports/intraday_decision_panel_491/intraday_decision_panel.csv.gz`
  - Entry-decision and position-management rows with scanner metadata, as-of intraday features,
    ETF context, position state, and oracle action labels.

## Implementation

- Add `scripts/train_intraday_entry_exit_policy.py`.
- Add `tests/scripts/test_train_intraday_entry_exit_policy.py`.
- Emit artifacts under `sweeps/reports/intraday_entry_exit_policy_490/`.

## Modeling

- Train separate dependency-free softmax linear classifiers:
  - `entry_policy`: `enter_now`, `wait`, `avoid_bad_entry`.
  - `management_policy`: `exit_loser`, `scratch_or_reduce`, `protect_profit`, `hold_winner`,
    `do_not_cut_runner`, `hold_or_wait`.
- Use expanding-window validation by `scan_date`; no random splits.
- Compare to simple rule baselines derived only from as-of intraday and position state.

## Safety

- Exclude oracle/future columns, action labels, reasons, route buckets, outcome/return horizon
  columns, and free-text source details from model features.
- Keep source flags, scanner ranks/scores, checkpoint, intraday bars, ETF context, and position
  state when available.

## Outputs

- OOF predictions with date, symbol, row type, as-of timestamp, labels, predicted action,
  probabilities, scanner metadata, and feature hash.
- Metrics by policy, action, source bucket, and month.
- Feature diagnostics from fold coefficients.
- Model artifact JSON for later local replay integration.
