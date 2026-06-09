# BCT Scanner Denominator Ranks Plan

Issue: #431

## Objective
Test whether George-style top-list alignment needs per-day denominator context rather than only absolute chart values.

## Steps
1. Add optional per-date denominator rank/percentile features to the offline learned ranker.
2. Keep default learned-ranker behavior unchanged unless `--use-denominator-ranks` is enabled.
3. Compare baseline pairwise+sector against pairwise+sector+denominator ranks on the same George labels and date-grouped OOF folds.
4. Record metrics in `research/scanner-alignment/experiment_log.csv` and a short report.
5. Verify with unit tests, ledger validation, mypy, and pytest before PR.

## Backlog
- #431 denominator-relative rank features.
- #434 TC2000-style sector and industry breadth features.
- #435 LambdaMART learning-to-rank benchmark.
- #433 positive-unlabeled and two-stage reranking.
- #432 runtime handoff gate.
