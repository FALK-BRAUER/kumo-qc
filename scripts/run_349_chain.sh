#!/usr/bin/env bash
# #349 hunt chain: wait for the running Q1+Q3 trace (bmpc57yrg) to finish, then gather Q2+Q4 (idempotent,
# skips already-traced), then run both graders. Strictly SEQUENTIAL — never 2 full-warmup BTs at once
# (OOM-safe at the 7.75GB Docker cap). Fail-loud: a grader SystemExit (a quarter missing trace) stops here.
set -uo pipefail
cd /Users/falk/projects/kumo-qc-362
export DOCKER_HOST="unix:///Users/falk/.docker/run/docker.sock"

echo "[chain] $(date '+%H:%M:%S') waiting for bmpc57yrg (run_349_trace.py) to exit..."
# The python parent blocks on its lean child, so parent-gone ⇒ all its BTs done. The chain launches
# its OWN run_349_trace.py only AFTER this loop, so no self-match during the wait.
while pgrep -f "scripts/run_349_trace.py" >/dev/null 2>&1; do
  sleep 20
done
echo "[chain] $(date '+%H:%M:%S') bmpc57yrg done. Gathering Q2+Q4 (idempotent)..."

python3 scripts/run_349_trace.py 2>&1 | tee /tmp/r349_q2q4.out
echo "[chain] $(date '+%H:%M:%S') trace gather done. Running graders..."

echo "===== run_353_manual =====" | tee /tmp/r349_graders.out
python3 scripts/run_353_manual.py 2>&1 | tee -a /tmp/r349_graders.out
echo "===== run_352_composite =====" | tee -a /tmp/r349_graders.out
python3 scripts/run_352_composite.py 2>&1 | tee -a /tmp/r349_graders.out
echo "[chain] $(date '+%H:%M:%S') CHAIN COMPLETE."
