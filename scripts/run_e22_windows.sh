#!/bin/bash
# E22 Active Return Gate - All 6 Windows Backtest Runner

cd /Users/falk/projects/kumo-qc

# Window 2: Feb-Jul 2025
echo "=== W2: Feb-Jul 2025 ==="
cat > algorithm/performance_bct/config.json << 'EOF'
{
    "local-id": 679828420,
    "parameters": {
        "warmup_days": "750",
        "weekly_kijun_exit": "True",
        "cloud_exit": "True",
        "start_year": "2025",
        "start_month": "2",
        "start_day": "1",
        "end_year": "2025",
        "end_month": "7",
        "end_day": "31"
    }
}
EOF
lean backtest algorithm/performance_bct 2>&1 | grep -E "(STATISTICS|Orders|Return|Sharpe|Win Rate|Drawdown)"

# Window 3: Mar-Aug 2025
echo "=== W3: Mar-Aug 2025 ==="
cat > algorithm/performance_bct/config.json << 'EOF'
{
    "local-id": 679828420,
    "parameters": {
        "warmup_days": "750",
        "weekly_kijun_exit": "True",
        "cloud_exit": "True",
        "start_year": "2025",
        "start_month": "3",
        "start_day": "1",
        "end_year": "2025",
        "end_month": "8",
        "end_day": "31"
    }
}
EOF
lean backtest algorithm/performance_bct 2>&1 | grep -E "(STATISTICS|Orders|Return|Sharpe|Win Rate|Drawdown)"

# Window 4: Apr-Sep 2025
echo "=== W4: Apr-Sep 2025 ==="
cat > algorithm/performance_bct/config.json << 'EOF'
{
    "local-id": 679828420,
    "parameters": {
        "warmup_days": "750",
        "weekly_kijun_exit": "True",
        "cloud_exit": "True",
        "start_year": "2025",
        "start_month": "4",
        "start_day": "1",
        "end_year": "2025",
        "end_month": "9",
        "end_day": "30"
    }
}
EOF
lean backtest algorithm/performance_bct 2>&1 | grep -E "(STATISTICS|Orders|Return|Sharpe|Win Rate|Drawdown)"

# Window 5: May-Oct 2025
echo "=== W5: May-Oct 2025 ==="
cat > algorithm/performance_bct/config.json << 'EOF'
{
    "local-id": 679828420,
    "parameters": {
        "warmup_days": "750",
        "weekly_kijun_exit": "True",
        "cloud_exit": "True",
        "start_year": "2025",
        "start_month": "5",
        "start_day": "1",
        "end_year": "2025",
        "end_month": "10",
        "end_day": "31"
    }
}
EOF
lean backtest algorithm/performance_bct 2>&1 | grep -E "(STATISTICS|Orders|Return|Sharpe|Win Rate|Drawdown)"

# Window 6: Jun-Nov 2025
echo "=== W6: Jun-Nov 2025 ==="
cat > algorithm/performance_bct/config.json << 'EOF'
{
    "local-id": 679828420,
    "parameters": {
        "warmup_days": "750",
        "weekly_kijun_exit": "True",
        "cloud_exit": "True",
        "start_year": "2025",
        "start_month": "6",
        "start_day": "1",
        "end_year": "2025",
        "end_month": "11",
        "end_day": "30"
    }
}
EOF
lean backtest algorithm/performance_bct 2>&1 | grep -E "(STATISTICS|Orders|Return|Sharpe|Win Rate|Drawdown)"

# FY2025 Full Year
echo "=== FY2025: Jan-Dec 2025 ==="
cat > algorithm/performance_bct/config.json << 'EOF'
{
    "local-id": 679828420,
    "parameters": {
        "warmup_days": "750",
        "weekly_kijun_exit": "True",
        "cloud_exit": "True",
        "start_year": "2025",
        "start_month": "1",
        "start_day": "1",
        "end_year": "2025",
        "end_month": "12",
        "end_day": "31"
    }
}
EOF
lean backtest algorithm/performance_bct 2>&1 | grep -E "(STATISTICS|Orders|Return|Sharpe|Win Rate|Drawdown)"

echo "=== ALL WINDOWS COMPLETE ==="
