#!/bin/bash
# P0 gate check: prevent experiment features with default="true" from reaching main
# Usage: ./scripts/check-defaults.sh [file_path]
# If no file provided, checks algorithm/performance_bct/main.py

FILE="${1:-algorithm/performance_bct/main.py}"

if [ ! -f "$FILE" ]; then
    echo "ERROR: File not found: $FILE"
    exit 1
fi

# Check for get_parameter calls with hardcoded "true" as the DEFAULT argument
# Pattern: get_parameter("name", "true") — the second argument is the literal string "true"
# This does NOT match: get_parameter("name", str(self.CONSTANT)).lower() == "true"
MATCHES=$(grep -nE 'get_parameter\s*\(\s*"[^"]+"\s*,\s*"true"\s*\)' "$FILE" || true)

if [ -n "$MATCHES" ]; then
    echo "❌ P0 VIOLATION: Found get_parameter with hardcoded default='true'"
    echo ""
    echo "$MATCHES"
    echo ""
    echo "RULE: All experiment features must default to 'false'."
    echo "Enable via --parameter flag during testing."
    echo "Fix: Change default from \"true\" to \"false\" or use a class constant."
    exit 1
fi

echo "✅ No hardcoded default='true' violations found in $FILE"
exit 0
