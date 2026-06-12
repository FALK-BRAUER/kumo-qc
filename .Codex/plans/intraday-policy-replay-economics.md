# Intraday Policy Replay Economics (#490 Correction)

## Problem

PR #496 trained a clean supervised baseline, but it did not satisfy #490. The missing step is
turning predicted actions into simulated trades and economic diagnostics.

## Corrected Deliverable

- Add `scripts/replay_intraday_entry_exit_policy.py`.
- Reuse #490 fold models for as-of-safe OOF scoring.
- Reconstruct position features from the #491 panel and completed 5-minute bars.
- Simulate earliest `enter_now`, then exit on `exit_loser`, `scratch_or_reduce`, or
  `protect_profit`; otherwise mark at close.
- Compare `model_policy` against `baseline_rules` in a trade ledger and candidate-level summary.

## Outputs

- `sweeps/reports/intraday_policy_replay_490/trade_ledger.csv.gz`
- `sweeps/reports/intraday_policy_replay_490/candidate_outcomes.csv.gz`
- `sweeps/reports/intraday_policy_replay_490/summary_metrics.csv`
- `sweeps/reports/intraday_policy_replay_490/source_bucket_metrics.csv`
- `sweeps/reports/intraday_policy_replay_490/intraday_policy_replay_report.md`
- `sweeps/reports/intraday_policy_replay_490/manifest.json`

## Verification

- Unit tests cover fold-model routing, earliest-entry replay, baseline comparison, and summary
  metrics.
- Smoke run on a limited panel must produce real trade rows.
- Full run must report realized same-day return, win rate, bad-entry participation, optimal-entry
  participation, runner participation, exit action mix, and source-bucket diagnostics.

## Non-Goals

- This is not QC Cloud deployment.
- This is not yet multi-day LEAN parity.
- George-only fairness still depends on #489.
