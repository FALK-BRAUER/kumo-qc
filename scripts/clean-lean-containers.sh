#!/bin/bash
# P0: Clean up STOPPED/EXITED LEAN Docker containers before backtests
# Prevents state leakage and data subscription pollution
# SAFE for multi-worker environments — NEVER kills running containers

echo "Checking for stopped/exited lean containers..."

# Only select STOPPED or DEAD lean containers — NEVER running ones
STOPPED_CONTAINERS=$(docker ps -aq --filter "name=lean" --filter "status=exited" 2>/dev/null)
DEAD_CONTAINERS=$(docker ps -aq --filter "name=lean" --filter "status=dead" 2>/dev/null)

ALL_STOPPED="${STOPPED_CONTAINERS}${DEAD_CONTAINERS}"

if [ -n "$ALL_STOPPED" ]; then
    echo "Removing $(echo "$ALL_STOPPED" | wc -w) stopped lean containers..."
    echo "$ALL_STOPPED" | xargs docker rm 2>/dev/null
    echo "✅ Cleaned stopped containers."
else
    echo "✅ No stopped lean containers found."
fi

# Safety check: warn if running containers exist
RUNNING=$(docker ps -q --filter "name=lean" 2>/dev/null)
if [ -n "$RUNNING" ]; then
    echo "⚠️  WARNING: $(echo "$RUNNING" | wc -w) lean container(s) still RUNNING."
    echo "    Do NOT start a new BT until these complete."
    echo "    Running containers:"
    docker ps --filter "name=lean" --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"
fi

echo "Ready for fresh backtest."
