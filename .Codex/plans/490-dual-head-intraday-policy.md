# #490 Dual-Head Intraday Policy Plan

## Objective
Build the next #490 intraday entry/exit improvement as an actual retrain, not another threshold layer over the v1 softmax.

## Branch
- Worktree: `/Users/falk/projects/kumo-qc-490-dual-head-policy`
- Branch: `codex/490-dual-head-policy`
- Base: `codex/490-entry-policy-v3`

## Implementation
1. Add `scripts/train_intraday_entry_exit_dual_head_policy.py`.
   - Reuse #490 feature engineering and walk-forward linear softmax training.
   - Train binary entry heads:
     - `entry_bad_risk_head`: bad bucket versus non-bad.
     - `entry_winner_preservation_head`: optimal/runner-positive versus not.
     - `entry_ready_head`: oracle entry-ready versus not-ready.
   - Train binary management heads:
     - `management_exit_risk_head`: exit/scratch/protect versus hold.
     - `management_runner_preservation_head`: runner-preserve/hold-winner versus not.
   - Write artifacts to `sweeps/reports/intraday_entry_exit_policy_490_dual_head/`.

2. Extend `scripts/replay_intraday_entry_exit_policy.py`.
   - Add a `dual_head_policy` replay variant.
   - Read the dual-head artifact separately from the existing v1 model artifact.
   - Score entry heads and management heads by fold.
   - Translate head probabilities into entry/management actions with fixed, documented policy rules.
   - Include the dual-head variant in reports and promotion gates.

3. Tests.
   - Add focused train tests for target construction and artifact shape.
   - Add focused replay tests for dual-head entry and management action translation.

4. Run artifacts.
   - `python3 scripts/train_intraday_entry_exit_dual_head_policy.py`
   - `python3 scripts/replay_intraday_entry_exit_policy.py`

5. Decision gate.
   - Promote only if bad-entry delta versus baseline is <= -15 points, optimal capture >= 70%, and runner capture >= 72%.
   - If it fails, document the missing signal rather than retuning scanner thresholds.

## Verification
- `git diff --check`
- `python3 -m pytest tests/scripts/test_train_intraday_entry_exit_policy.py tests/scripts/test_replay_intraday_entry_exit_policy.py tests/scripts/test_train_intraday_entry_exit_dual_head_policy.py`
- Full dual-head training and replay commands above.

## Result
Executed. `dual_head_policy` is not promotable:
- Bad-entry delta versus baseline: `-21.969` points.
- Optimal capture: `50.928%`, below the `70%` gate.
- Runner capture: `72.695%`, above the `72%` gate.
- Same-day average return: `0.0470%`, better than v2/v3 but achieved by becoming too selective.

Missing signal: current #491 intraday features learn bad-risk better than winner-preservation. Entry
winner-preservation recall is `28.003%`; entry-readiness recall is `24.496%`.
