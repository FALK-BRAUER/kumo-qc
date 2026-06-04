#!/usr/bin/env bash
# #370 M3 launcher: WAIT for the hard-stop chain (run_hardstop_chain.sh) to free the cap-1 Docker,
# then run the #370 acceptance (FY+Q1 first = merge gate, then the rest). M2 (complete cache) is
# already built. Sequential cap-1 (full-warmup baselines are 4.3GB). Posts nothing — the runner logs.
set -uo pipefail
cd /Users/falk/projects/kumo-qc-368
export DOCKER_HOST="unix:///Users/falk/.docker/run/docker.sock"
echo "[370-chain] $(date '+%H:%M:%S') waiting for hard-stop chain + its lean to free Docker..."
while pgrep -f "run_hardstop_chain.sh" >/dev/null 2>&1 || pgrep -f "lean backtest" >/dev/null 2>&1; do
  sleep 20
done
echo "[370-chain] $(date '+%H:%M:%S') Docker free. Running #370 acceptance (FY+Q1 first)..."
python3 scripts/run_370_acceptance.py fy q1 q3 q2 q4 w5 w6 2>&1 | tee /tmp/m3_acceptance.out
echo "[370-chain] $(date '+%H:%M:%S') M3 ACCEPTANCE COMPLETE."
