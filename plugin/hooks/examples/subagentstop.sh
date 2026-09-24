#!/usr/bin/env bash
# =============================================================================
# SubagentStop hook — when a subagent finishes responding
# =============================================================================
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "~/.claude/projects/.../abc123.jsonl",
#     "cwd": "/Users/.../my-project",
#     "permission_mode": "default",
#     "hook_event_name": "SubagentStop",
#     "stop_hook_active": false,
#     "agent_id": "def456",
#     "agent_type": "Explore",
#     "agent_transcript_path": "~/.claude/projects/.../abc123/subagents/agent-def456.jsonl",
#     "last_assistant_message": "Analysis complete. Found 3 potential issues...",
#     "background_tasks": [],
#     "session_crons": []
#   }
# I get no duration or exit-status field. I also see Claude Code fire this event
# for some of its own internal agents; for those, I can get an empty agent_type ("").
#
# Common uses:
#   - Closing the loop on tracked subagent dispatches (I pair it with
#     SubagentStart via agent_id to compute duration myself)
#   - Keeping a short record of what each subagent reported
#   - Completion pings for long-running subagents
#
# Exit behavior: I know stdout goes to the debug log. With exit 2 (or JSON
# {"decision": "block", ...}) I keep the SUBAGENT running with my reason as
# its next instruction. To add context to the parent session after a subagent
# returns, I use a PostToolUse hook on the Agent tool instead.
#
# I register it in ~/.claude/settings.json under hooks.SubagentStop, optionally
# with a matcher on agent type.
# =============================================================================

set -u

PAYLOAD=$(cat)
FIELDS=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    msg = (d.get('last_assistant_message') or '').replace('\n', ' ')
    print(d.get('agent_type', '') or '<internal>', d.get('agent_id', '<unknown>'),
          msg, sep='\x1f', end='')
except Exception as exc:
    print(f'subagentstop.sh: I could not parse the hook payload ({exc})', file=sys.stderr)
    print('<unknown>', '<unknown>', '', sep='\x1f', end='')
")
IFS=$'\x1f' read -r AGENT_TYPE AGENT_ID LAST_MESSAGE <<< "$FIELDS"

# --- Example: subagent completion log ----------------------------------------

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/subagents.log"

# Sanitize: strip control chars + cap length. Payload string fields can
# carry newlines/ANSI escapes that forge log entries.
AGENT_TYPE_SAFE=$(printf '%s' "$AGENT_TYPE" | tr -d '\000-\037\177' | cut -c1-100)
AGENT_ID_SAFE=$(printf '%s' "$AGENT_ID" | tr -d '\000-\037\177' | cut -c1-100)
LAST_MESSAGE_SAFE=$(printf '%s' "$LAST_MESSAGE" | tr -d '\000-\037\177' | cut -c1-200)

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] END   %s id=%s "%s"\n' "$TIMESTAMP" "$AGENT_TYPE_SAFE" "$AGENT_ID_SAFE" "$LAST_MESSAGE_SAFE" >> "$LOG_FILE" 2>/dev/null

exit 0
