# Scanner Alternate Entry Replay Plan

## Goal

Complete the next #465 slice by replaying scanner opportunities with changed entry prices,
not just next-open gates. The output should show whether realistic confirmation entries improve
the Kumo/George opportunity surface before any ML or LEAN integration work.

## Files

- `scripts/replay_scanner_alternate_entries.py`
  - Read the #463 opportunity panel.
  - Filter to a configurable opportunity subset, defaulting to `kumo_top100_or_george`.
  - Read local raw intraday parquet from `/Users/falk/projects/kumo-trader/data/intraday`.
  - Replay `next_open`, `first_hour_confirm`, `prior_session_high_breakout`, and
    `pullback_1pct_reclaim` entry assumptions.
  - Reuse #464 path-label math for MFE, MAE, target/stop order, runner, winner, and bad-trade
    labels.
  - Write compact tracked summaries under `sweeps/reports/scanner_entry_replay_465/`.

- `tests/scripts/test_replay_scanner_alternate_entries.py`
  - Unit-test trigger detection with synthetic intraday bars.
  - Verify delayed entries do not include pre-entry same-day bars in the replay path.

- `sweeps/reports/scanner_entry_replay_465/`
  - Generated compact research output and README.

## Verification

- Run focused pytest for the new script plus the #464 label tests.
- Run the replay script on the default `kumo_top100_or_george` subset.
- Inspect `entry_assumption_summary.csv` and `entry_replay_report.md` for trigger rates,
  return, runner, and bad-trade differences.
