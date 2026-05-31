#!/usr/bin/env bash
# Reproduce the champion_asis MASTER BASE-BASELINE (research/parity/base-baseline-2025.md).
# MEASUREMENT ONLY — does NOT modify champion_asis, dist/, or any phase. Builds champion_asis
# into THROWAWAY lean projects (dist_tmp pattern; gitignored backtests/), runs local full-FY +
# 6-window, and (optionally) the cloud full-FY via the v2 driver with the Step-A window nulled.
#
# Provenance pin (must match dist/_metadata.py): config_hash e573e84b1ce1 · data_fingerprint
# 90f2d7e3 · commit 369b5d9 (mainV2 / chore/base-baseline).
#
# Usage:
#   bash scripts/measure_base_baseline.sh local     # local full-FY (the canonical -0.616)
#   bash scripts/measure_base_baseline.sh windows   # 6-window FY2025 bi-monthly distribution
#   bash scripts/measure_base_baseline.sh cloud      # deploy + run cloud full-FY (ground truth)
set -uo pipefail
export DOCKER_HOST="${DOCKER_HOST:-unix:///Users/falk/.docker/run/docker.sock}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-/Users/falk/projects/kumo-qc/.venv/bin/python}"
cd "$ROOT"

build_proj() {  # $1 = project dir, $2 = local-id
  "$PY" -c "import sys;sys.path[:0]=['src','build'];from build.cloud_package import build;from pathlib import Path;r=build('strategies.champion_asis',dist_dir=Path('$1'));print('built',r.config_hash)"
  "$PY" - "$1/config.json" "$2" <<'PYJSON'
import json,sys,os
p,lid=sys.argv[1],int(sys.argv[2])
if not os.path.exists(p):
    json.dump({"algorithm-language":"Python","parameters":{}},open(p,'w'))
c=json.load(open(p)); c['algorithm-language']='Python'; c.setdefault('parameters',{}); c['local-id']=lid
json.dump(c,open(p,'w'),indent=2)
PYJSON
}

case "${1:-help}" in
  local)
    build_proj algorithm/v2_champion_asis 777000777
    lean backtest algorithm/v2_champion_asis ;;
  windows)
    build_proj algorithm/v2_champion_asis_win 777111777
    # bi-monthly FY2025 split; NOISY/trade-starved (see the doc) — robustness distribution, not signal.
    bash scripts/measure_253_windows.sh algorithm/v2_champion_asis_win asis ;;
  cloud)
    # The v2 driver bakes a Step-A short window by default; null it for the full-FY ground-truth run.
    TMP=/tmp/qc_v2_cloud_baseline.py
    cp scripts/qc_v2_cloud.py "$TMP"
    "$PY" - "$TMP" "$ROOT" <<'PYPATCH'
import sys
p,root=sys.argv[1],sys.argv[2]
t=open(p).read()
t=t.replace('STEP_A_WINDOW = "    START_DATE = (2025, 6, 2)\\n    END_DATE = (2025, 6, 16)\\n"',
            'STEP_A_WINDOW = None  # BASELINE full-FY: no short-window injection')
t=t.replace('DIST = Path(__file__).resolve().parents[1] / "dist"', f'DIST = Path("{root}/dist")')
open(p,'w').write(t)
PYPATCH
    "$PY" "$TMP" deploy
    "$PY" "$TMP" run "base-baseline-fullFY-e573e84b" 120 ;;
  *)
    echo "usage: $0 {local|windows|cloud}" ;;
esac
