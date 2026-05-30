#!/usr/bin/env bash
# worker-preflight.sh — MANDATORY before any worker runs a local LEAN backtest
# or edits algorithm/**/main.py. Aborts if the worker is operating in the shared
# main tree instead of its own git worktree.
#
# Why: all workers share one checkout by default. Two workers running BTs or
# editing main.py in the same tree corrupt each other (2026-05-29 P0 incident:
# duplicate cloud pushes + contradictory results + a fabricated diff).
#
# Usage (worker runs this FIRST, before any BT/main.py work):
#   bash scripts/worker-preflight.sh <worker_id>
# Exit 0 = isolated worktree, safe to proceed. Exit 1 = abort, create a worktree.

set -euo pipefail

WORKER_ID="${1:-unknown}"
MAIN_TREE="/Users/falk/projects/kumo-qc"
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null || echo '')"

if [[ -z "$TOPLEVEL" ]]; then
  echo "PREFLIGHT FAIL ($WORKER_ID): not in a git repo." >&2
  exit 1
fi

# git-dir reveals if this checkout is a linked worktree (.git/worktrees/...)
GIT_DIR="$(git rev-parse --git-dir 2>/dev/null || echo '')"
IS_WORKTREE="no"
if [[ "$GIT_DIR" == *"/worktrees/"* ]]; then
  IS_WORKTREE="yes"
fi

if [[ "$TOPLEVEL" == "$MAIN_TREE" || "$IS_WORKTREE" == "no" ]]; then
  cat >&2 <<MSG
PREFLIGHT FAIL ($WORKER_ID): you are in the SHARED main tree ($TOPLEVEL).
Local backtests / main.py edits here collide with other workers.

Create your own worktree FIRST (per CLAUDE.md:92 Worktree Regime):
  cd $MAIN_TREE
  git worktree add ../kumo-qc-$WORKER_ID -b feat/<exp-id>
  rm -rf ../kumo-qc-$WORKER_ID/data
  ln -s $MAIN_TREE/data ../kumo-qc-$WORKER_ID/data
  cd ../kumo-qc-$WORKER_ID
Then re-run this preflight. ABORTING.
MSG
  exit 1
fi

echo "PREFLIGHT OK ($WORKER_ID): isolated worktree $TOPLEVEL — safe to run BT / edit main.py."
exit 0
