# Scanner Exit Policy Research Plan

## Goal

Complete issue #466 by deriving exit and realization policy candidates from the scanner
opportunity paths. The harness must evaluate realized plus marked-to-market return so we do not
reward policies that only look good because they close winners and ignore open runner value.

## Files

- `scripts/analyze_scanner_exit_policies.py`
  - Read #464 opportunity path labels and #463 sector/ETF metadata.
  - Filter to a configurable opportunity subset, defaulting to `kumo_top100_or_george`.
  - Rebuild regular-session daily bars from local raw parquet.
  - Simulate hold, fixed target/stop, partial take + trail, giveback trail, swing-low trail,
    time stop, and ETF weakness exit policies.
  - Write compact labels, summaries, examples, manifest, and a Markdown report under
    `sweeps/reports/scanner_exit_policies_466/`.

- `tests/scripts/test_analyze_scanner_exit_policies.py`
  - Unit-test fixed target/stop ordering.
  - Unit-test partial target plus trail math.
  - Unit-test giveback, time-stop, and ETF weakness behavior.

- `sweeps/reports/scanner_exit_policies_466/`
  - Generated compact research output for issue #466.

## Verification

- Run focused pytest for the new script.
- Run ruff on the new script/test.
- Run the full report on the default opportunity subset.
- Inspect policy summaries for 2-3 deployable LEAN/QC candidates.
