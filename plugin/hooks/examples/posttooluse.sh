#!/usr/bin/env bash
# =============================================================================
# PostToolUse hook — after a tool call succeeds
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
# I see tool_response's shape vary by tool. From Bash I get stdout, stderr, and
# interrupted, but NO exit code. I treat duration_ms as optional. For failed
# tool calls I get PostToolUseFailure instead, not this event.
#
# Common uses:
#   - Logging tool outcomes and timing
#   - Adding context for Claude after specific tools (JSON additionalContext)
#   - Triggering downstream automation (e.g., lint after Write/Edit)
#   - Capturing diff metrics (files changed per Write/Edit batch)
#
# Exit behavior: I know stdout goes to the debug log, not to Claude, unless I
# print JSON output (e.g. hookSpecificOutput.additionalContext). With exit 2 I
# show my stderr to Claude, but the tool already ran, so I undo nothing. I get
# only non-blocking errors from other non-zero exits.
#
# I register it in ~/.claude/settings.json under hooks.PostToolUse with a
# matcher (e.g. "Bash", or "Write|Edit").
# =============================================================================

set -u

PAYLOAD=$(cat)

# --- Example: Bash duration + interrupted-flag log for observability ---------
# I use it to spot slow or frequently interrupted commands across sessions.

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/bash-outcomes.log"

# I extract all three fields in one Python call, joined by the ASCII unit
# separator (0x1f). I picked it over a tab because it doesn't collapse when a
# field is empty.
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
    print(f'posttooluse.sh: I could not parse the hook payload ({exc})', file=sys.stderr)
    print('', 'n/a', 'n/a', sep='\x1f', end='')
")
IFS=$'\x1f' read -r TOOL_NAME DURATION_MS INTERRUPTED <<< "$FIELDS"

if [[ "$TOOL_NAME" == "Bash" ]]; then
    # Sanitize: I take the values from the payload, so I strip control chars.
    DURATION_SAFE=$(printf '%s' "$DURATION_MS" | tr -d '\000-\037\177' | cut -c1-20)
    INTERRUPTED_SAFE=$(printf '%s' "$INTERRUPTED" | tr -d '\000-\037\177' | cut -c1-10)
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    printf '[%s] duration_ms=%s interrupted=%s\n' "$TIMESTAMP" "$DURATION_SAFE" "$INTERRUPTED_SAFE" >> "$LOG_FILE" 2>/dev/null
fi

exit 0
