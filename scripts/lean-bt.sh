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

# ROOT FIX: all worktrees share config.json local-id (git-tracked) → lean resolves
# them as the SAME project and runs one canonical copy regardless of cwd (2026-05-29
# contamination root cause). Assign a unique local-id per worktree so lean keeps
# them distinct. This alone prevents cross-worktree code mix-ups.
CFG="algorithm/performance_bct/config.json"
if [[ -f "$CFG" ]]; then
  UID_NUM=$(( ( $(pwd | cksum | cut -d' ' -f1) % 800000000 ) + 100000000 ))
  python3 - "$CFG" "$UID_NUM" <<'PY'
import json,sys
cfg,uid=sys.argv[1],int(sys.argv[2])
c=json.load(open(cfg)); c['local-id']=uid; json.dump(c,open(cfg,'w'),indent=2)
PY
  echo "[lean-bt] set unique local-id=$UID_NUM for $(pwd)"
fi

# Concurrency: unique local-id (above) fully isolates worktrees — proven safe by
# the 2026-05-29 parallel-safety test (2 concurrent distinct-code runs, no cross-
# contamination). So the flock is OPT-IN now (LEAN_LOCK=1), default OFF = parallel.
if [[ "${LEAN_LOCK:-0}" == "1" ]]; then
  exec 9>"$LOCK"
  echo "[lean-bt] $(date +%T) LEAN_LOCK=1 — waiting for serial lock..."
  flock 9
fi
echo "[lean-bt] $(date +%T) running in $(pwd): lean backtest $*"

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
