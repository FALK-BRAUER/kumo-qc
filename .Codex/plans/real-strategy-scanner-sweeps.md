# Real Strategy Scanner Sweeps

## Goal
Run the opt-in LambdaMART scanner ranker against actual realized strategy candidates, not the old
baseline whose FY return was mostly unrealized open PnL.

## GitHub Tracking
- #453: 12-cell real strategy x scanner matrix.
- #454: ignored local LambdaMART artifact restore/export if missing.
- #451: realized strategy candidate promotion.

## Candidate Matrix
- `strategies.realized_giveback_no_bull`
- `strategies.realized_target_04_fast_take`
- `strategies.realized_target_08_let_run`

Scanner settings per strategy:
- scanner off/control
- LambdaMART Top-15
- LambdaMART Top-20
- LambdaMART Top-25

## Implementation Steps
1. Share the George-range phase stack in `src/strategies/realized_george_factory.py`.
2. Add the two additional non-fixture realized candidates.
3. Add `real_strategy_scanner` to `sweeps/grids/scanner_ranker.py`.
4. Update `scripts/run_scanner_ranker_sweep.py` so each variant carries `base_module`, isolates
   multi-base run roots, and writes realized/unrealized diagnostics.
5. Add tests for candidate configs, pack shape, base-module replacement, run-dir isolation, and
   diagnostics parsing.
6. Run unit tests, then a January smoke, then FY2025 matrix if the artifact is present.

## Done Criteria
- Default champion remains unchanged.
- Scanner ranker remains opt-in.
- Sweep command exists and reports return, DD, orders, realized net, unrealized, closed trades, and
  closed win rate.
- Artifact sha is recorded before reporting scanner-gated results.
