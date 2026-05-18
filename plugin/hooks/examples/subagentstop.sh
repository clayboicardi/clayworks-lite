#!/usr/bin/env bash
# =============================================================================
# SubagentStop hook — fires when a dispatched subagent completes
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "subagent_type": "...",
#     "session_id": "...",          # parent session
#     "subagent_session_id": "...", # the subagent's own session ID
#     "duration_seconds": 123,
#     "exit_status": "success" | "error" | "timeout",
#     "ended_at": "ISO-8601"
#   }
#
# Common uses:
#   - Close the loop on tracked subagent dispatches
#   - Surface error/timeout outcomes for review
#   - Telegram ping for long-running subagents
#   - Compute parallel-work telemetry
#
# Exit behavior: stdout is logged, not surfaced to either session.
#
# Register in ~/.claude/settings.json under hooks.SubagentStop.
# =============================================================================

set -u

PAYLOAD=$(cat)
SUBAGENT_TYPE=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('subagent_type', '<unknown>'), end='')
except Exception:
    print('<unknown>', end='')
")
DURATION=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('duration_seconds', 0), end='')
except Exception:
    print(0, end='')
")
EXIT_STATUS=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('exit_status', 'unknown'), end='')
except Exception:
    print('unknown', end='')
")

# --- Example: log subagent completion --------------------------------------

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/subagents.log"

# Sanitize: strip control chars + cap length. Payload string fields can
# carry newlines/ANSI escapes that forge log entries.
SUBAGENT_TYPE_SAFE=$(printf '%s' "$SUBAGENT_TYPE" | tr -d '\000-\037\177' | cut -c1-100)
EXIT_STATUS_SAFE=$(printf '%s' "$EXIT_STATUS" | tr -d '\000-\037\177' | cut -c1-50)

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] END   %s status=%s duration=%ds\n' "$TIMESTAMP" "$SUBAGENT_TYPE_SAFE" "$EXIT_STATUS_SAFE" "$DURATION" >> "$LOG_FILE" 2>/dev/null

exit 0
