#!/usr/bin/env bash
# P1 hard-stop chain — GATE-FIRST, fail-fast, sequential cap-1 (OOM-safe full-warmup).
#   1. mainV2-ref     : plain champion FY-full (kumo-qc-mainv2, choices=() == S1-0.0 body)
#   2. baseline-0.0   : mainV2 + lever @0.0 FY-full (here)
#   3. BASE-VALIDITY GATE: fills(ref) == fills(0.0) byte-identical? FAIL → STOP (don't trust any X).
#   4. X>0 sweep      : 0.08 0.12 0.15 0.20 FY-full (here) — only if the gate passed.
set -uo pipefail
HS=/Users/falk/projects/kumo-qc-hardstop
MV=/Users/falk/projects/kumo-qc-mainv2
export DOCKER_HOST="unix:///Users/falk/.docker/run/docker.sock"
log(){ echo "[hardstop-chain] $(date '+%H:%M:%S') $*"; }

log "STEP 1/4 — plain mainV2 reference FY-full (IDENTICAL S1 config 65c0cf447168, no-lever code, continuous_weekly=True)"
cd "$MV" && python3 scripts/run_hardstop_sweep.py 0.0 2>&1 | tee /tmp/hs_ref.out
log "STEP 2/4 — baseline-0.0 FY-full (mainV2 + lever @0.0)"
cd "$HS" && python3 scripts/run_hardstop_sweep.py 0.0 2>&1 | tee /tmp/hs_baseline.out

log "STEP 3/4 — BASE-VALIDITY GATE (fills ref == 0.0; same config 65c0cf447168, code differs only by the guarded lever)"
cd "$HS" && python3 scripts/gate_base_validity.py \
  "$MV/sweeps/runs/65c0cf447168/fy2025_full/backtests" \
  "$HS/sweeps/runs/65c0cf447168/fy2025_full/backtests" 2>&1 | tee /tmp/hs_gate.out
if ! grep -q "GATE PASS" /tmp/hs_gate.out; then
  log "GATE FAILED — base is NOT a clean mainV2 reproduction. STOP. Trust no X result."
  exit 1
fi

log "STEP 4/4 — gate passed. X>0 hard-stop sweep (0.08 0.12 0.15 0.20)"
cd "$HS" && python3 scripts/run_hardstop_sweep.py 0.08 0.12 0.15 0.20 2>&1 | tee /tmp/hs_xsweep.out
log "CHAIN COMPLETE — results/hardstop_sweep_fy.csv"
