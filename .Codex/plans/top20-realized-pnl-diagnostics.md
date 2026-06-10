# #455 Top20 Realized PnL Diagnostics Plan

## Goal
Convert the LambdaMART top20 scanner edge from lower negative unrealized PnL into
understandable, repeatable realized-PnL improvement without changing the production champion.

## Phase 1: Baseline Diagnostics
- Inspect the committed #453 report summaries and available LEAN result JSON/order-event artifacts.
- Build or extend a diagnostics extractor that compares scanner-off versus scanner-top20 for:
  `realized_giveback_no_bull`, `realized_target_04_fast_take`, and `realized_target_08_let_run`.
- Produce per-symbol summaries covering orders, closed PnL, open/unrealized PnL, MFE, MAE,
  giveback, days held, exit reason, and symbols added/removed by top20.

## Phase 2: Mechanism Read
- Identify the symbols/trades responsible for the unrealized gap.
- Separate useful scanner removals from harmful removals and harmful retained names.
- Check whether top20 improves selection quality or mainly suppresses late/stale open losers.
- Record findings in a small report under `sweeps/reports`.

## Phase 3: Targeted Exit/Realization Sweep
- Design a top20-only follow-up sweep using the top 2-3 real strategy bases.
- Prefer focused variations: stale-no-new-MFE exits, tighter giveback after minimum MFE, age caps,
  sector caps, and end-of-year liquidation diagnostics.
- Preserve phase modularity and keep scanner opt-in.

## Phase 4: Verification And Publishing
- Add focused tests for any new diagnostics, phase, or runner behavior.
- Run a January smoke if runtime strategy behavior changes.
- Run FY2025 with `--workers 3`.
- Commit only code/docs/small report summaries; do not commit raw `sweeps/runs` artifacts.
- Push a PR and comment the diagnostics/sweep result on #455.
