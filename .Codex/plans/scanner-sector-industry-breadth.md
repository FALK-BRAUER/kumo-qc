# Scanner Sector/Industry Breadth Substrate

Issue: #442

## Objective

Build sector/industry breadth features that can be produced from live scanner candidates without George/OCR/watchlist evidence, then rerun the clean_top2000 scanner leaderboard to see whether the deployable feature set can approach the promotion threshold.

## Constraints

- Research labels stay research-only.
- Feature definitions must be reproducible locally and in QC cloud, or explicitly marked blocked.
- The candidate panel is the denominator for ranks and breadth; George rows are never the denominator.
- No runtime promotion unless date-grouped OOF recall@10 beats the current promotion threshold.

## Steps

1. Audit existing scanner alignment harnesses, runtime scanner/ranking phases, sector rotation code, and feature parity markers.
2. Identify the available sector/industry taxonomy source for local Massive simulation and QC cloud runtime.
3. Implement a deployable candidate-panel breadth transformer:
   - sector and industry denominator counts;
   - counts and percentages for BCT >= 6, BCT >= 7, and positive daily return;
   - median day return and relative volume by group.
4. Add focused tests for mapping, missing mapping fallbacks, and breadth aggregation.
5. Update research docs, `feature_parity_columns.csv`, and `FOR_FALK.md`.
6. Rerun the clean_top2000 leaderboard and record recall@5/10/20/50/100.
7. Commit, push, and open a PR linked to #442.

## Verification

- Unit tests pass for the new breadth transformer.
- Existing scanner alignment harness can consume the deployable breadth columns.
- Leaderboard output states whether the result beats 101/306 and whether it reaches the promotion gate.
