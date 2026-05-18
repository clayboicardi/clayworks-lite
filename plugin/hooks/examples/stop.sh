#!/usr/bin/env bash
# =============================================================================
# Stop hook — fires when Claude completes its turn (returns to await user)
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "session_id": "...",
#     "transcript_path": "...",
#     "turn_count": 42,
#     "model": "claude-opus-4-7"
#   }
#
# Common uses:
#   - End-of-turn cleanup (temp files, half-open handles)
#   - Observability grading (background subprocess that grades the turn)
#   - Memory consolidation triggers (e.g., 24h-gated dream-style processes)
#   - Telegram pings for completion notification
#
# Exit behavior: stdout is logged but not surfaced to the user. Stop hooks
# should be FAST (<1s ideal); long-running work belongs in a background
# subprocess that the Stop hook spawns and immediately returns from.
#
# Register in ~/.claude/settings.json under hooks.Stop.
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

# --- Example: append a turn-end timestamp to a per-session log ---------------
# Useful for spotting long turns (e.g., turn-count diff vs wall time).

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/turns-$(date +%Y-%m-%d).log"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] %s\n' "$TIMESTAMP" "$SESSION_ID" >> "$LOG_FILE" 2>/dev/null

# --- Example: gated 24h trigger pattern (skeleton) ---------------------------
# Many "dream-style" consolidation flows want to run at most once per day.
# Convention: track last-fired timestamp in a sentinel file.
#
# SECURITY: the background-job script path is security-sensitive — anything
# that can write to ~/.claude/scripts/your-daily-job.sh gets `nohup bash`
# execution on every Stop trigger after the 24h gate. Pin the path to a
# directory only your account can write to (chmod 700 on the dir, chmod 700
# on the script). Don't put it anywhere a shared service could touch.
#
# SENTINEL="$HOME/agent/.last-stop-trigger"
# # File mtime via Python for cross-platform portability — `date -r` diverges
# # between GNU (reads file mtime) and BSD/macOS (treats arg as epoch seconds).
# SENTINEL_MTIME=$(python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$SENTINEL" 2>/dev/null || echo 0)
# if [[ ! -f "$SENTINEL" ]] || [[ $(( $(date +%s) - SENTINEL_MTIME )) -gt 86400 ]]; then
#     date +%s > "$SENTINEL"
#     # Fire the gated work in background so we don't block CC's exit.
#     ( nohup bash ~/.claude/scripts/your-daily-job.sh >/dev/null 2>&1 & )
# fi

exit 0
