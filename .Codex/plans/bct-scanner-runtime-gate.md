# BCT Scanner Runtime Promotion Gate Plan

Issue: #432

## Objective

Define and test the handoff gate that prevents lab-only scanner-alignment lift from being promoted into
QC runtime or cloud without a clean feature source.

## Steps

1. Link the gate from `research/scanner-alignment/` and document promotion criteria.
2. Use `feature_parity_columns.csv` as the explicit feature-level allow/deny list.
3. Make George-derived deny rows explicit and keep the audit generator consistent.
4. Add a validator for gate artifacts and tests for unsafe classifications.
5. Verify with focused tests, ledger/gate validators, mypy, and pytest before PR.
