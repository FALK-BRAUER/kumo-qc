#!/bin/bash
# Pre-commit hook: P0 gate check for default="true" violations
# Blocks any commit that introduces get_parameter with hardcoded default="true"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check main.py
"$SCRIPT_DIR/check-defaults.sh" "$REPO_ROOT/algorithm/performance_bct/main.py"

if [ $? -ne 0 ]; then
    echo ""
    echo "COMMIT BLOCKED: Fix the violation above before committing."
    exit 1
fi

# Also check any modified Python files
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)

for file in $STAGED_PY; do
    if [ -f "$REPO_ROOT/$file" ]; then
        "$SCRIPT_DIR/check-defaults.sh" "$REPO_ROOT/$file"
        if [ $? -ne 0 ]; then
            echo ""
            echo "COMMIT BLOCKED: Fix the violation in $file before committing."
            exit 1
        fi
    fi
done

exit 0
