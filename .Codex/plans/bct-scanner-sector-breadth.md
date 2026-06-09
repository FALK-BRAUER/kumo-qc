# BCT Scanner Sector Breadth Plan

Issue: #434

## Objective
Test whether TC2000-style sector and industry breadth facts improve George top-list alignment after #431 denominator ranks.

## Steps
1. Add optional sector/industry breadth feature ingestion to the offline learned ranker.
2. Keep baseline behavior unchanged unless `--use-sector-breadth` is enabled.
3. Compare pairwise+sector+denominator-ranks against the same setup plus breadth features.
4. Record OOF metrics in `research/scanner-alignment/experiment_log.csv` and a short report.
5. Verify with unit tests, ledger validation, mypy, and pytest before PR.

## Boundary
These features are research-only until the runtime handoff gate proves a matching live TC2000/QC mapping.
