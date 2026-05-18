#!/usr/bin/env bash
# =============================================================================
# SessionEnd hook — fires when a Claude Code session terminates
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "session_id": "...",
#     "transcript_path": "...",
#     "ended_at": "ISO-8601 timestamp",
#     "duration_seconds": 1234
#   }
#
# Common uses:
#   - Append a session summary line to a daily log
#   - Persist final state (e.g., dump current TODO list)
#   - Trigger downstream automation (deploy, notify, etc.)
#   - Capture session-length telemetry
#
# Exit behavior: stdout is suppressed (session is already ending). Non-zero
# exit is logged. SessionEnd hooks should be FAST — CC waits for them before
# fully exiting.
#
# Register in ~/.claude/settings.json under hooks.SessionEnd.
# =============================================================================

set -u

PAYLOAD=$(cat)
SESSION_ID=$(printf '%s' "$PAYLOAD" | python -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', '<unknown>'), end='')
except Exception:
    print('<unknown>', end='')
")
DURATION=$(printf '%s' "$PAYLOAD" | python -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('duration_seconds', 0), end='')
except Exception:
    print(0, end='')
")

# --- Example: log session-end telemetry to a daily log -----------------------

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/sessions-$(date +%Y-%m).log"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
MINUTES=$(( DURATION / 60 ))
printf '[%s] session=%s duration=%dm\n' "$TIMESTAMP" "$SESSION_ID" "$MINUTES" >> "$LOG_FILE" 2>/dev/null

exit 0
