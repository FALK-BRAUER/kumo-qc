#!/usr/bin/env bash
# Serialized lean-backtest wrapper — prevents compile-cache cross-contamination
# between concurrent worktree runs (2026-05-29 incident: e40c ran e40b's code).
#
# Concurrent `lean backtest` with the same project name share lean's compile
# cache → one run executes another's compiled code. flock serializes ALL lean
# backtests machine-wide so only one compiles/runs at a time. Workers may still
# work in parallel; only the lean step is mutually exclusive.
#
# Usage (from inside a worktree):
#   MARKER=e40c_qqq_regime bash scripts/lean-bt.sh algorithm/performance_bct --parameter ...
# MARKER (optional) = a VERSION_MARKER substring expected in the executed code;
# the wrapper greps the run's code/main.py snapshot to confirm YOUR code ran.

set -uo pipefail
LOCK=/tmp/kumo-qc-lean.lock
MARKER="${MARKER:-}"
DOCKER_HOST="${DOCKER_HOST:-unix:///Users/falk/.docker/run/docker.sock}"
export DOCKER_HOST

exec 9>"$LOCK"
echo "[lean-bt] $(date +%T) waiting for machine-wide lean lock..."
flock 9
echo "[lean-bt] $(date +%T) lock acquired in $(pwd) — running: lean backtest $*"

lean backtest "$@"
rc=$?

# Post-run contamination guard: confirm the executed code is THIS worktree's.
latest="$(ls -td algorithm/performance_bct/backtests/* 2>/dev/null | head -1)"
if [[ -n "$MARKER" && -f "$latest/code/main.py" ]]; then
  if grep -q "$MARKER" "$latest/code/main.py"; then
    echo "[lean-bt] ✅ VERSION_MARKER OK ('$MARKER') in $latest — own code ran."
  else
    echo "[lean-bt] ⚠️ VERSION_MARKER '$MARKER' NOT FOUND in $latest/code/main.py — POSSIBLE CONTAMINATION. Do NOT trust this result."
    rc=1
  fi
fi
# Always print which marker the executed code actually had, for the record.
[[ -f "$latest/code/main.py" ]] && echo "[lean-bt] executed code markers: $(grep -o 'VERSION_MARKER|[a-z0-9_]*' "$latest/code/main.py" | sort -u | tr '\n' ' ')"
echo "[lean-bt] $(date +%T) done (rc=$rc), releasing lock."
exit $rc
