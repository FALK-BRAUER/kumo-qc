# BCT Scanner LambdaMART Plan

Issue: #435

## Objective
Benchmark a grouped learning-to-rank model against the dependency-free pairwise linear selector.

## Steps
1. Add an optional LightGBM LambdaMART harness that reuses the existing scanner panel, feature matrix, and date-grouped OOF protocol.
2. Keep LightGBM as an optional research dependency; CI must still pass without it.
3. Evaluate LambdaMART with sector context, denominator ranks, and sector breadth enabled.
4. Record metrics in `research/scanner-alignment/experiment_log.csv` and a short report.
5. Verify with unit tests, ledger validation, mypy, and pytest before PR.
