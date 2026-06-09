# BCT Scanner PU And Two-Stage Plan

Issue: #433

## Objective
Test whether weak-negative weighting and stage1-topN/stage2 reranking improve the LambdaMART top10 selector.

## Steps
1. Add optional positive/negative sample weights to the LambdaMART harness.
2. Add optional two-stage mode: train stage1 on the full panel, select topN per date, train stage2 on that subset, and rerank validation topN.
3. Compare against #435 LambdaMART baseline under the same date-grouped OOF protocol.
4. Record metrics in `research/scanner-alignment/experiment_log.csv` and a short report.
5. Verify with tests, ledger validation, mypy, and pytest before PR.
