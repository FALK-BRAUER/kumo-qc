# #479 Dynamic Scanner Realized Sweep

Goal: test the LambdaMART scanner as a dynamic score-threshold filter on real realized strategy
bases, without deployable fixed Top-X slots or fixed day/session exits.

## Scope

- Base strategies:
  - `strategies.realized_giveback_no_bull`
  - `strategies.realized_target_04_fast_take`
  - `strategies.realized_target_08_let_run`
- Scanner modes:
  - scanner off control
  - score loose: `scanner_ranker_min_score=-0.25`, `scanner_ranker_top_x=0`
  - score medium: `scanner_ranker_min_score=-0.20`, `scanner_ranker_top_x=0`
  - score strict: `scanner_ranker_min_score=-0.16`, `scanner_ranker_top_x=0`
- Existing entry/exit phases stay unchanged.

## Verification

1. Add `dynamic_realized_scanner` sweep pack and focused grid tests.
2. Run the scanner grid and runner tests.
3. Copy the ignored local LambdaMART artifact into `storage/`.
4. Run a January smoke with six variants, `workers=3`.
5. If the smoke is sane, run the full FY2025 twelve-cell pack with `workers=3`.
6. Commit only small summaries/reports; raw LEAN runs and the model artifact stay ignored.

## Read Criteria

- Compare return, drawdown, orders, realized net, unrealized, closed trades, and closed win rate.
- Prefer rows that improve realized quality and total return without relying on a static slot/day rule.
- If thresholds collapse to zero trades or clone the control, recalibrate before expanding.
