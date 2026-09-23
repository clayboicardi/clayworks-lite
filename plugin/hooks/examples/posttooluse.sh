#!/usr/bin/env bash
# =============================================================================
# PostToolUse hook — fires AFTER a tool call succeeds
# =============================================================================
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "/Users/.../.claude/projects/.../<session>.jsonl",
#     "cwd": "/Users/.../my-project",
#     "permission_mode": "default",
#     "hook_event_name": "PostToolUse",
#     "tool_name": "Bash",
#     "tool_input": { "command": "npm test", "description": "Run tests" },
#     "tool_response": { "stdout": "...", "stderr": "...", "interrupted": false,
#                        "isImage": false },
#     "tool_use_id": "toolu_01ABC123...",
#     "duration_ms": 1234
#   }
# tool_response's shape depends on the tool. Bash reports stdout, stderr, and
# interrupted; it does NOT report an exit code. duration_ms is optional.
# Failed tool calls fire PostToolUseFailure instead, not this event.
#
# Common uses:
#   - Log tool outcomes and timing
#   - Add context for Claude after specific tools (JSON additionalContext)
#   - Trigger downstream automation (e.g., lint after Write/Edit)
#   - Capture diff metrics (files changed per Write/Edit batch)
#
# Exit behavior: stdout goes to the debug log, not to Claude, unless you print
# JSON output (e.g. hookSpecificOutput.additionalContext). Exit 2 shows your
# stderr to Claude; the tool already ran, so nothing gets undone. Other
# non-zero exits are non-blocking errors.
#
# Register in ~/.claude/settings.json under hooks.PostToolUse with a matcher
# (e.g. "Bash", or "Write|Edit").
# =============================================================================

set -u

PAYLOAD=$(cat)

# --- Example: log Bash duration + interrupted flag for observability ---------
# Useful for spotting slow or frequently interrupted commands across sessions.

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/bash-outcomes.log"

# One Python call extracts all three fields, joined by the ASCII unit
# separator (0x1f). Unlike a tab, it doesn't collapse when a field is empty.
FIELDS=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    resp = d.get('tool_response') or {}
    interrupted = resp.get('interrupted') if isinstance(resp, dict) else None
    print(d.get('tool_name', ''), d.get('duration_ms', 'n/a'),
          'n/a' if interrupted is None else str(bool(interrupted)).lower(),
          sep='\x1f', end='')
except Exception as exc:
    print(f'posttooluse.sh: could not parse the hook payload ({exc})', file=sys.stderr)
    print('', 'n/a', 'n/a', sep='\x1f', end='')
")
IFS=$'\x1f' read -r TOOL_NAME DURATION_MS INTERRUPTED <<< "$FIELDS"

if [[ "$TOOL_NAME" == "Bash" ]]; then
    # Sanitize: the values come from the payload; strip control chars.
    DURATION_SAFE=$(printf '%s' "$DURATION_MS" | tr -d '\000-\037\177' | cut -c1-20)
    INTERRUPTED_SAFE=$(printf '%s' "$INTERRUPTED" | tr -d '\000-\037\177' | cut -c1-10)
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    printf '[%s] duration_ms=%s interrupted=%s\n' "$TIMESTAMP" "$DURATION_SAFE" "$INTERRUPTED_SAFE" >> "$LOG_FILE" 2>/dev/null
fi

exit 0
