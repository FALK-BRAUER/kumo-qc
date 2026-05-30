#!/bin/bash
# E26 Inverse-Vol Sizing — All 6 Windows + FY2025 Backtest Runner

cd /Users/falk/projects/kumo-qc

run_window() {
    local label=$1
    local sy=$2 sm=$3 sd=$4 ey=$5 em=$6 ed=$7
    echo "=== ${label} ==="
    cat > algorithm/performance_bct/config.json << CONF
{
    "local-id": 679828420,
    "parameters": {
        "warmup_days": "750",
        "weekly_kijun_exit": "True",
        "cloud_exit": "True",
        "start_year": "${sy}",
        "start_month": "${sm}",
        "start_day": "${sd}",
        "end_year": "${ey}",
        "end_month": "${em}",
        "end_day": "${ed}"
    }
}
CONF
    lean backtest algorithm/performance_bct 2>&1 | grep -E "(STATISTICS|Total Orders|Compounding Annual|Sharpe Ratio|Win Rate|Drawdown|Total Fees)"
    echo ""
}

run_window "W1: Jan-Jun 2025"  2025 1 1  2025 6  30
run_window "W2: Feb-Jul 2025"  2025 2 1  2025 7  31
run_window "W3: Mar-Aug 2025"  2025 3 1  2025 8  31
run_window "W4: Apr-Sep 2025"  2025 4 1  2025 9  30
run_window "W5: May-Oct 2025"  2025 5 1  2025 10 31
run_window "W6: Jun-Nov 2025"  2025 6 1  2025 11 30
run_window "FY2025: Jan-Dec 2025" 2025 1 1 2025 12 31

echo "=== E26 ALL WINDOWS COMPLETE ==="
