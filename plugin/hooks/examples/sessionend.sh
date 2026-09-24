#!/usr/bin/env bash
# =============================================================================
# SessionEnd hook — when a Claude Code session ends
# =============================================================================
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "/Users/.../.claude/projects/.../<session>.jsonl",
#     "cwd": "/Users/.../my-project",
#     "hook_event_name": "SessionEnd",
#     "reason": "prompt_input_exit"
#   }
# I get reason as one of: clear | resume | logout | prompt_input_exit | other
# I get no duration or end-timestamp field; I compute those myself (e.g.
# from the transcript file's timestamps) when I need them.
#
# Common uses:
#   - Appending a session summary line to a daily log
#   - Persisting final state (e.g., dumping the current TODO list)
#   - Capturing session-end telemetry
#
# Exit behavior: I can't block the session from ending with SessionEnd, and I
# know Claude Code discards JSON output. With a non-zero exit I only show
# stderr to the user.
#
# TIMEOUT: I get a short shared budget for SessionEnd hooks, 1.5 seconds by
# default. I raise it (up to 60s) with a per-hook "timeout" in settings.json or
# with the CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS environment variable. I keep
# the work tiny, or hand anything slow to a detached background process.
#
# I register it in ~/.claude/settings.json under hooks.SessionEnd. I add a matcher
# (e.g. "prompt_input_exit|logout") to skip /clear and /resume switches.
# =============================================================================

set -u

PAYLOAD=$(cat)
FIELDS=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', '<unknown>'), d.get('reason', 'unknown'), sep='\x1f', end='')
except Exception as exc:
    print(f'sessionend.sh: I could not parse the hook payload ({exc})', file=sys.stderr)
    print('<unknown>', 'unknown', sep='\x1f', end='')
")
IFS=$'\x1f' read -r SESSION_ID REASON <<< "$FIELDS"

# --- Example: session-end reason in a monthly log ----------------------------

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/sessions-$(date +%Y-%m).log"

# Sanitize: I strip payload strings, since they can carry newlines/ANSI escapes
# that forge log lines.
SESSION_ID_SAFE=$(printf '%s' "$SESSION_ID" | tr -d '\000-\037\177' | cut -c1-100)
REASON_SAFE=$(printf '%s' "$REASON" | tr -d '\000-\037\177' | cut -c1-50)

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] session=%s reason=%s\n' "$TIMESTAMP" "$SESSION_ID_SAFE" "$REASON_SAFE" >> "$LOG_FILE" 2>/dev/null

exit 0
