#!/usr/bin/env bash
# =============================================================================
# Stop hook — fires each time Claude finishes responding
# =============================================================================
# Stop fires after EVERY response, not when the session exits (that's
# SessionEnd). It skips responses you interrupt, and API-error endings fire
# StopFailure instead.
#
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "/Users/.../.claude/projects/.../<session>.jsonl",
#     "cwd": "/Users/.../my-project",
#     "permission_mode": "default",
#     "hook_event_name": "Stop",
#     "stop_hook_active": false,
#     "last_assistant_message": "I've completed the refactoring. ...",
#     "background_tasks": [],
#     "session_crons": []
#   }
# stop_hook_active is true when Claude is already continuing because a Stop
# hook blocked it earlier. Check it before blocking again, or you can loop.
#
# Common uses:
#   - End-of-turn cleanup (temp files, half-open handles)
#   - Observability grading (background subprocess that grades the turn)
#   - Memory consolidation triggers (e.g., 24h-gated dream-style processes)
#   - Completion pings (desktop notification, chat message)
#
# Exit behavior: stdout goes to the debug log, not to Claude or the user.
# Exit 2 (or JSON {"decision": "block", "reason": "..."}) BLOCKS the stop:
# Claude keeps working with your reason as its next instruction. Don't do that
# by accident. Other non-zero exits are non-blocking errors.
#
# Keep Stop hooks FAST (<1s ideal): they run after every response. Long work
# belongs in a background subprocess that the hook spawns and returns from.
#
# Register in ~/.claude/settings.json under hooks.Stop (no matcher support).
# =============================================================================

set -u

PAYLOAD=$(cat)
FIELDS=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', '<unknown>'),
          str(bool(d.get('stop_hook_active', False))).lower(),
          sep='\x1f', end='')
except Exception as exc:
    print(f'stop.sh: could not parse the hook payload ({exc})', file=sys.stderr)
    print('<unknown>', 'false', sep='\x1f', end='')
")
IFS=$'\x1f' read -r SESSION_ID STOP_HOOK_ACTIVE <<< "$FIELDS"

# --- Example: append a turn-end timestamp to a per-day log -------------------
# Useful for spotting long turns (timestamps vs. transcript size), and for
# seeing how often a Stop hook forced Claude to continue.

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/turns-$(date +%Y-%m-%d).log"

SESSION_ID_SAFE=$(printf '%s' "$SESSION_ID" | tr -d '\000-\037\177' | cut -c1-100)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] %s stop_hook_active=%s\n' "$TIMESTAMP" "$SESSION_ID_SAFE" "$STOP_HOOK_ACTIVE" >> "$LOG_FILE" 2>/dev/null

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
#     # Fire the gated work in the background so this hook returns immediately.
#     ( nohup bash ~/.claude/scripts/your-daily-job.sh >/dev/null 2>&1 & )
# fi

exit 0
