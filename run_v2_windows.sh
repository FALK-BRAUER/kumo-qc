#!/bin/bash
# Run W1-W6 rolling 6-month windows for V2 QQQ dual MA gate
set -uo pipefail

WINDOWS=(
  "W1:2025:01:01:2025:06:30"
  "W2:2025:02:01:2025:07:31"
  "W3:2025:03:01:2025:08:31"
  "W4:2025:04:01:2025:09:30"
  "W5:2025:05:01:2025:10:31"
  "W6:2025:06:01:2025:11:30"
)

echo "=== V2 QQQ Dual MA Window Runs ===" | tee /tmp/v2_windows.log

for win in "${WINDOWS[@]}"; do
  IFS=':' read -r name sy sm sd ey em ed <<< "$win"
  echo -e "\n--- Running $name ($sm/$sd - $em/$ed) ---" | tee -a /tmp/v2_windows.log
  
  MARKER=v2_qqq_50_200 bash scripts/lean-bt.sh algorithm/performance_bct \
    --parameter start_year $sy \
    --parameter start_month $sm \
    --parameter start_day $sd \
    --parameter end_year $ey \
    --parameter end_month $em \
    --parameter end_day $ed \
    2>&1 | tee -a /tmp/v2_windows.log | grep -E "STATISTICS:: (Sharpe|Total Orders|Drawdown|Compounding Annual|Win Rate)"
    
  echo "--- $name complete ---" | tee -a /tmp/v2_windows.log
done

echo -e "\n=== All windows complete ===" | tee -a /tmp/v2_windows.log
