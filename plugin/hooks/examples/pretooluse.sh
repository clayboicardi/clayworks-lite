#!/usr/bin/env bash
# =============================================================================
# PreToolUse hook — fires BEFORE a tool call executes
# =============================================================================
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "/Users/.../.claude/projects/.../<session>.jsonl",
#     "cwd": "/Users/.../my-project",
#     "permission_mode": "default",
#     "hook_event_name": "PreToolUse",
#     "tool_name": "Write",
#     "tool_input": { "file_path": "/abs/path/file.txt", "content": "..." },
#     "tool_use_id": "toolu_01ABC123..."
#   }
# Inside a subagent I also get agent_id and agent_type in the payload.
#
# Common uses:
#   - Sandbox enforcement (block Write/Edit outside a specific dir)
#   - Audit logging (record every tool call with timestamp)
#   - Resource guards (block expensive operations during low-budget time)
#
# Exit behavior:
#   - Exit 0            → no decision; I leave it to the normal permission flow
#   - Exit 2            → I BLOCK the tool call and send stderr to Claude as
#                         the reason. I block only with exit 2.
#   - Any other non-zero → non-blocking error: I still see the tool call run.
#                         I never use `exit 1` for a guard.
#   - For finer control (allow / deny / ask), I exit 0 and print a JSON
#     hookSpecificOutput.permissionDecision object instead.
#
# IMPORTANT: I get PreToolUse hooks firing on EVERY matching tool call, so I
# keep them FAST (<100ms ideal); I'd add latency to every interaction with a
# slow one. I can't block the call with a timed-out command hook, so I never
# treat a hook as a hard security boundary; I use permission rules for that.
#
# Register in ~/.claude/settings.json under hooks.PreToolUse with a matcher:
#   { "matcher": "Write|Edit|NotebookEdit", "hooks": [{...}] }
# =============================================================================

set -u

PAYLOAD=$(cat)
TOOL_NAME=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_name', ''), end='')
except Exception as exc:
    print(f'pretooluse.sh: I could not parse the hook payload ({exc})', file=sys.stderr)
    pass
")

# --- Example: audit log of every Write/Edit/NotebookEdit ---------------------
# Useful for auditing what Claude touched. Replace with your own logic.

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/tool-audit.log"

case "$TOOL_NAME" in
    Write|Edit|NotebookEdit)
        TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        FILE_PATH=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', {})
    print(ti.get('file_path') or ti.get('notebook_path') or '<unknown>', end='')
except Exception as exc:
    print(f'pretooluse.sh: I could not parse the hook payload ({exc})', file=sys.stderr)
    print('<unknown>', end='')
")
        # Sanitize: strip control chars + cap length. A maliciously-crafted
        # tool_input.file_path could carry newlines/ANSI escapes that forge
        # log entries or attack a `cat`-the-log terminal session.
        FILE_PATH_SAFE=$(printf '%s' "$FILE_PATH" | tr -d '\000-\037\177' | cut -c1-500)
        printf '[%s] %s %s\n' "$TIMESTAMP" "$TOOL_NAME" "$FILE_PATH_SAFE" >> "$LOG_FILE" 2>/dev/null
        ;;
esac

# --- Example: block writes outside ~/Projects/ -------------------------------
# I'd uncomment + customize this for sandbox enforcement. I use `exit 2` here
# because it's the code that blocks. I get file paths absolute, with the
# platform's native separators (backslashes on Windows), so I adjust the
# pattern there.
#
# case "$TOOL_NAME" in
#     Write|Edit)
#         FILE_PATH=$(printf '%s' "$PAYLOAD" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))")
#         case "$FILE_PATH" in
#             "$HOME/Projects/"*)
#                 ;;  # allowed
#             *)
#                 echo "PreToolUse hook: I blocked this write because I allow writes only inside ~/Projects/ ($FILE_PATH)" >&2
#                 exit 2
#                 ;;
#         esac
#         ;;
# esac

exit 0
