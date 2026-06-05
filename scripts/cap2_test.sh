#!/usr/bin/env bash
# cap-2 byte-identical test (HQ gate): run 3 cells SERIAL + same 3 via fleet (warm-1 + 2 concurrent).
# Assert parallel result == serial result per cell (proves the race is gone, not hidden). Sample
# docker stats for warmup-PEAK RSS (sizes WARMUP_GATE / --workers when Docker RAM is raised).
set -u
cd /Users/falk/projects/kumo-qc-340
CELLS="score_s8 profit_t2 profit_t3"
PEAK=/tmp/cap2_peak.txt; : > "$PEAK"

echo "=== SERIAL baseline (runs_cap2s) ==="
for c in $CELLS; do python3 scripts/run_cell.py "$c" q1 cap2s; done

echo "=== PARALLEL (runs_cap2p) + peak sampler ==="
( while pgrep -f "run_fleet|run_cell" >/dev/null 2>&1; do
    docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' 2>/dev/null | grep lean_cli >> "$PEAK"
    sleep 2
  done ) &
SAMPLER=$!
python3 scripts/run_fleet.py --workers 3 --runs cap2p --windows q1 $CELLS
kill "$SAMPLER" 2>/dev/null

echo "=== COMPARE serial vs parallel (floor-proxy must be IDENTICAL per cell) ==="
for c in $CELLS; do
  s=$(python3 scripts/realized_ledger.py "sweeps/runs_cap2s/$c/w1_2025q1/fb0e2fa2cb67/w1_2025q1" 2025-03-31 2>/dev/null | grep FLOOR-PROXY)
  p=$(python3 scripts/realized_ledger.py "sweeps/runs_cap2p/$c/w1_2025q1/fb0e2fa2cb67/w1_2025q1" 2025-03-31 2>/dev/null | grep FLOOR-PROXY)
  [ "$s" = "$p" ] && verdict="IDENTICAL ✓" || verdict="DIFFER ✗✗✗"
  echo "  $c: $verdict"
  echo "     serial:   $s"
  echo "     parallel: $p"
done
echo "=== WARMUP-PEAK (max lean_cli MemUsage during parallel) ==="
sort -t/ -k1 "$PEAK" 2>/dev/null | awk '{print $3}' | sed 's/GiB//;s/MiB/e-3*1024/' | sort -rn | head -3
echo "raw peak samples (top 5 by mem):"; sort -k3 -hr "$PEAK" 2>/dev/null | head -5
echo "=== cap-2 test DONE ==="
