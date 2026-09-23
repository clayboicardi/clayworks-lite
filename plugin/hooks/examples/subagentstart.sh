#!/usr/bin/env bash
# =============================================================================
# SubagentStart hook — fires when Claude spawns (or resumes) a subagent
# =============================================================================
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "/Users/.../.claude/projects/.../<session>.jsonl",
#     "cwd": "/Users/.../my-project",
#     "hook_event_name": "SubagentStart",
#     "agent_id": "agent-abc123",
#     "agent_type": "Explore"
#   }
# agent_type is what a matcher filters on: built-in names like
# "general-purpose", "Explore", "Plan", a custom agent's frontmatter name, or a
# plugin-scoped name like "my-plugin:reviewer". The payload doesn't carry the
# task description.
#
# Common uses:
#   - Track parallel work (counter, dashboard, telemetry)
#   - Log delegated work for later auditing
#   - Inject context into the subagent (JSON hookSpecificOutput.additionalContext)
#
# Exit behavior: SubagentStart can't block the subagent. Plain stdout goes to
# the debug log; to give the subagent context, print JSON additionalContext.
# A non-zero exit shows a hook-error notice in the subagent's transcript.
#
# Register in ~/.claude/settings.json under hooks.SubagentStart, optionally
# with a matcher on agent type (e.g. "Explore|Plan").
# =============================================================================

set -u

PAYLOAD=$(cat)
FIELDS=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('agent_type', '<unknown>'), d.get('agent_id', '<unknown>'), sep='\x1f', end='')
except Exception as exc:
    print(f'subagentstart.sh: could not parse the hook payload ({exc})', file=sys.stderr)
    print('<unknown>', '<unknown>', sep='\x1f', end='')
")
IFS=$'\x1f' read -r AGENT_TYPE AGENT_ID <<< "$FIELDS"

# --- Example: log subagent dispatches for audit ------------------------------

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/subagents.log"

# Sanitize: strip control chars + cap length. Payload fields can carry
# newlines/ANSI escapes that forge log entries or attack a terminal session.
AGENT_TYPE_SAFE=$(printf '%s' "$AGENT_TYPE" | tr -d '\000-\037\177' | cut -c1-100)
AGENT_ID_SAFE=$(printf '%s' "$AGENT_ID" | tr -d '\000-\037\177' | cut -c1-100)

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '[%s] START %s id=%s\n' "$TIMESTAMP" "$AGENT_TYPE_SAFE" "$AGENT_ID_SAFE" >> "$LOG_FILE" 2>/dev/null

exit 0
