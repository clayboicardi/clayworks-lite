#!/usr/bin/env bash
# =============================================================================
# Stop hook — customized example (from hooks/examples/stop.sh)
# =============================================================================
# Fires when Claude completes its turn. Logs a one-line turn-end timestamp
# per session per day. Useful for spotting unusually long turns (timestamps
# vs. transcript size).
#
# The 24h-gated background-trigger pattern (e.g. dream-style consolidation)
# is commented out below — uncomment and pin a real script path when you
# have one to call.
# =============================================================================

set -u

PAYLOAD=$(cat)
SESSION_ID=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', '<unknown>'), end='')
except Exception:
    print('<unknown>', end='')
")

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/turns-$(date +%Y-%m-%d).log"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] %s\n' "$TIMESTAMP" "$SESSION_ID" >> "$LOG_FILE" 2>/dev/null

# --- 24h-gated background trigger (uncomment when you have something to run) ---
#
# SECURITY: pin the script path to a chmod-700 dir + chmod-700 script. Anything
# that can write to the pinned path gets `nohup bash` execution every Stop.
#
# SENTINEL="$HOME/agent/.last-stop-trigger"
# SENTINEL_MTIME=$(python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$SENTINEL" 2>/dev/null || echo 0)
# if [[ ! -f "$SENTINEL" ]] || [[ $(( $(date +%s) - SENTINEL_MTIME )) -gt 86400 ]]; then
#     date +%s > "$SENTINEL"
#     ( nohup bash ~/agent/scripts/daily-consolidation.sh >/dev/null 2>&1 & )
# fi

exit 0
