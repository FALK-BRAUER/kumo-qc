# Intraday Decision Panel #491

## Goal

Build the supervised data panel for the real scanner task: given a ranked daily scanner
candidate and as-of intraday data, produce decision-time rows for entry and position
management policy training.

## Inputs

- `sweeps/reports/scanner_trade_universe_482/scanner_trade_universe.csv.gz`
  - Daily scanner candidates, trade buckets, best entry, and best exit labels.
- `sweeps/reports/scanner_entry_replay_465/alternate_entry_labels.csv.gz`
  - Triggered entry assumptions and trigger timestamps.
- `sweeps/reports/scanner_exit_policies_466/exit_policy_labels.csv.gz`
  - Exit-policy context for later management labels.
- `/Users/falk/projects/kumo-trader/data/intraday/*.parquet`
  - Raw intraday bars used only up to each decision timestamp.

## Implementation

- Add `scripts/build_intraday_decision_panel.py`.
- Add `tests/scripts/test_build_intraday_decision_panel.py`.
- Emit artifacts under `sweeps/reports/intraday_decision_panel_491/`.
- Start with Kumo/George scanner rows already present in #482; George fairness improves once #489 exists.

## Row Types

- `entry_decision`: fixed next-session checkpoints: open, 15m, 30m, first hour, midday, close.
- `position_management`: checkpoints at or after the oracle/best entry time, with position-state features.

## Safety Rules

- Feature columns must be computed only from bars with `timestamp <= as_of_timestamp`.
- Future route, return, MFE/MAE, best-entry, and exit-policy fields are label columns only.
- No model training in this ticket.

## Verification

- Unit tests for label mapping, as-of feature slicing, no-entry cases, and row-type separation.
- Generate the full artifact and report coverage for missing intraday, 15m/hour, and Ichimoku features.
