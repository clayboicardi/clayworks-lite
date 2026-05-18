#!/usr/bin/env bash
# =============================================================================
# SubagentStart hook — fires when Claude dispatches a subagent via Agent tool
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "subagent_type": "general-purpose" | "Explore" | ...,
#     "session_id": "...",          # parent session
#     "subagent_session_id": "...", # the subagent's own session ID
#     "description": "...",         # short description from the Agent call
#     "started_at": "ISO-8601"
#   }
#
# Common uses:
#   - Track parallel work (counter, dashboard, telemetry)
#   - Log delegated tasks for later auditing
#   - Surface a warning if too many subagents are in flight
#
# Exit behavior: stdout is logged, not surfaced to either session.
#
# Register in ~/.claude/settings.json under hooks.SubagentStart.
# =============================================================================

set -u

PAYLOAD=$(cat)
SUBAGENT_TYPE=$(printf '%s' "$PAYLOAD" | python -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('subagent_type', '<unknown>'), end='')
except Exception:
    print('<unknown>', end='')
")
DESCRIPTION=$(printf '%s' "$PAYLOAD" | python -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('description', '<no description>'), end='')
except Exception:
    print('<no description>', end='')
")

# --- Example: log subagent dispatches for audit ------------------------------

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/subagents.log"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] START %s "%s"\n' "$TIMESTAMP" "$SUBAGENT_TYPE" "$DESCRIPTION" >> "$LOG_FILE" 2>/dev/null

exit 0
