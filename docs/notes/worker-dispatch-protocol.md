# Worker Dispatch Protocol

Mandatory template for orchestrators dispatching any task that runs a local LEAN
backtest or edits `algorithm/**/main.py`. Enforces worktree isolation (CLAUDE.md
Worktree Regime) and data integrity. Created 2026-05-29 after the shared-tree P0
incident (3 workers colliding in one checkout; one fabricated cloud-order data).

## Why this exists

Workers share one git checkout by default. Two BTs or two `main.py` edits in the
same tree corrupt each other. Without a dispatch gate, workers skip the worktree
regime and collide every session.

## Dispatch template (BT / main.py tasks)

Paste this into the task dispatch. The worker MUST ack before starting.

```
TASK: <experiment id / description>
ISOLATION REQUIRED — create your own worktree before any BT or main.py edit:

  cd /Users/falk/projects/kumo-qc
  git worktree add ../kumo-qc-<worker_id> -b feat/<exp-id>
  rm -rf ../kumo-qc-<worker_id>/data
  ln -s /Users/falk/projects/kumo-qc/data ../kumo-qc-<worker_id>/data
  cd ../kumo-qc-<worker_id>
  bash scripts/worker-preflight.sh <worker_id>     # must print PREFLIGHT OK

ACK REQUIRED before starting: reply "PREFLIGHT OK in worktree ../kumo-qc-<worker_id>".

SPEC:
  - <config / commit / parameters>
  - <window>
  - <deliverable: file path + format>

DATA INTEGRITY: report only real artifacts (BT output dir, order-events file,
verified API response). If a fetch is empty, say "no data" — NEVER fabricate or
assume parity. Cite the artifact path for every number you report.

CLEANUP: when accepted/rejected, PR or record result, then `git worktree remove`.
```

## Orchestrator checklist (per BT dispatch)

- [ ] Dispatch used the template above (worktree + preflight + ack requirement).
- [ ] Worker replied "PREFLIGHT OK in worktree <path>" BEFORE running anything.
- [ ] No two workers assigned BT work in the same tree at the same time.
- [ ] Critical findings spot-checked against ground truth (QC API / artifact on disk).
- [ ] One owner per cloud project push at a time (cloud pushes also collide).

## Non-BT tasks

Read-only work (enumeration, research docs, log/artifact analysis, API reads) does
NOT need a worktree — it cannot collide. Dispatch normally, but still apply the
data-integrity rule.
