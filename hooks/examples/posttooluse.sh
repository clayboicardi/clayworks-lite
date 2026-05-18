#!/usr/bin/env bash
# =============================================================================
# PostToolUse hook — fires AFTER a tool call returns
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "tool_name": "Bash" | "Edit" | "Write" | ...,
#     "tool_input": { ... },
#     "tool_response": { ... },  # the tool's return value
#     "session_id": "...",
#     "cwd": "/path/to/cwd"
#   }
#
# Common uses:
#   - Log tool outcomes (success/failure rates)
#   - React to specific errors (e.g., test failures → surface alert)
#   - Trigger downstream automation (e.g., on successful commit → push)
#   - Capture diff metrics (files changed per Write/Edit batch)
#
# Exit behavior: stdout is typically suppressed; this is an observe-only hook
# in most CC versions. Non-zero exit logs the failure but doesn't undo the tool.
#
# Register in ~/.claude/settings.json under hooks.PostToolUse with a matcher.
# =============================================================================

set -u

PAYLOAD=$(cat)
TOOL_NAME=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_name', ''), end='')
except Exception:
    pass
")

# --- Example: log Bash command exit codes for observability ------------------
# Useful for spotting recurring command failures across sessions.

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/bash-outcomes.log"

if [[ "$TOOL_NAME" == "Bash" ]]; then
    EXIT_CODE=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    resp = d.get('tool_response', {})
    print(resp.get('exit_code', 'n/a'), end='')
except Exception:
    print('n/a', end='')
")
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    printf '[%s] exit=%s\n' "$TIMESTAMP" "$EXIT_CODE" >> "$LOG_FILE" 2>/dev/null
fi

exit 0
