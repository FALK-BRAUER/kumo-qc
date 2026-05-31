#!/usr/bin/env bash
# #253 Phase-1 measurement: run a v2 project over the 6 FY2025 bi-monthly windows.
# Bakes each window's START/END into the project main.py (project copy only — NOT the tracked
# dist), runs lean backtest, and writes a one-line summary per window. NO cloud spend.
set -uo pipefail
export DOCKER_HOST="${DOCKER_HOST:-unix:///Users/falk/.docker/run/docker.sock}"

PROJ="$1"          # e.g. algorithm/v2_champion_entry
LABEL="$2"         # e.g. entry  | asis
OUT="research/experiments/253_measure_${LABEL}.csv"
echo "window,start,end,sharpe,net_profit_pct,max_dd_pct,total_orders,bt_dir" > "$OUT"

# 6 bi-monthly FY2025 windows (W1..W6).
WINDOWS=(
  "W1 2025 1 1 2025 2 28"
  "W2 2025 3 1 2025 4 30"
  "W3 2025 5 1 2025 6 30"
  "W4 2025 7 1 2025 8 31"
  "W5 2025 9 1 2025 10 31"
  "W6 2025 11 1 2025 12 31"
)

MAIN="$PROJ/main.py"
# strip any prior baked date overrides, keep a clean BCTAlgorithm
python3 - "$MAIN" <<'PY'
import re,sys
p=sys.argv[1]; t=open(p).read()
# remove previously baked START_DATE/END_DATE override lines
t=re.sub(r"\n    START_DATE = \([^)]*\)\n    END_DATE = \([^)]*\)\n","\n",t)
open(p,'w').write(t)
PY

for w in "${WINDOWS[@]}"; do
  read -r name sy sm sd ey em ed <<< "$w"
  # bake this window's dates onto the BCTAlgorithm subclass (project copy only)
  python3 - "$MAIN" "$sy" "$sm" "$sd" "$ey" "$em" "$ed" <<'PY'
import re,sys
p,sy,sm,sd,ey,em,ed=sys.argv[1:8]
t=open(p).read()
t=re.sub(r"\n    START_DATE = \([^)]*\)\n    END_DATE = \([^)]*\)\n","\n",t)
ins=f"\n    START_DATE = ({sy}, {sm}, {sd})\n    END_DATE = ({ey}, {em}, {ed})\n"
t=t.replace("class BCTAlgorithm(BctEngineAlgorithm):\n    STRATEGY_CONFIG = STRATEGY_CONFIG",
            "class BCTAlgorithm(BctEngineAlgorithm):\n    STRATEGY_CONFIG = STRATEGY_CONFIG"+ins)
open(p,'w').write(t)
PY
  echo "[$LABEL] running $name $sy-$sm-$sd .. $ey-$em-$ed"
  lean backtest "$PROJ" >/dev/null 2>&1
  BT=$(ls -td "$PROJ"/backtests/* 2>/dev/null | head -1)
  # parse the result json (statistics block)
  read -r sharpe ret dd orders <<< "$(python3 - "$BT" <<'PY'
import json,glob,sys,os
bt=sys.argv[1]
js=[f for f in glob.glob(os.path.join(bt,'*.json')) if 'order-events' not in f]
stat=None
for f in js:
    try: d=json.load(open(f))
    except Exception: continue
    s=d.get('statistics') or d.get('Statistics') or {}
    if not s and 'totalPerformance' in d: s=d
    if s:
        stat=s; break
def g(s,*keys):
    for k in keys:
        if k in s: return s[k]
    return ''
if stat is None:
    print("NA NA NA NA")
else:
    sh=g(stat,'Sharpe Ratio','SharpeRatio')
    ret=g(stat,'Net Profit','NetProfit').replace('%','').strip() if isinstance(g(stat,'Net Profit','NetProfit'),str) else g(stat,'Net Profit')
    dd=g(stat,'Drawdown').replace('%','').strip() if isinstance(g(stat,'Drawdown'),str) else g(stat,'Drawdown')
    orders=g(stat,'Total Orders','Total Trades','TotalTrades')
    print(f"{sh or 'NA'} {ret or 'NA'} {dd or 'NA'} {orders or 'NA'}")
PY
)"
  echo "$name,$sy-$sm-$sd,$ey-$em-$ed,$sharpe,$ret,$dd,$orders,$BT" >> "$OUT"
  echo "[$LABEL] $name -> sharpe=$sharpe ret=$ret dd=$dd orders=$orders"
done
echo "[$LABEL] DONE -> $OUT"
cat "$OUT"
