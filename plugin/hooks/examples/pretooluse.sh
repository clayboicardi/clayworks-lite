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
# Inside a subagent the payload also carries agent_id and agent_type.
#
# Common uses:
#   - Sandbox enforcement (block Write/Edit outside a specific dir)
#   - Audit logging (record every tool call with timestamp)
#   - Resource guards (block expensive operations during low-budget time)
#
# Exit behavior:
#   - Exit 0            → no decision; the normal permission flow applies
#   - Exit 2            → the tool call is BLOCKED; stderr goes to Claude as
#                         the reason. Exit 2 is the only code that blocks.
#   - Any other non-zero → non-blocking error: the tool call still runs.
#                         Never use `exit 1` for a guard.
#   - For finer control (allow / deny / ask), exit 0 and print a JSON
#     hookSpecificOutput.permissionDecision object instead.
#
# IMPORTANT: PreToolUse hooks fire on EVERY matching tool call. Keep them FAST
# (<100ms ideal). A slow hook adds latency to every interaction. A timed-out
# command hook does NOT block the call, so don't treat a hook as a hard
# security boundary; use permission rules for that.
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
    print(f'pretooluse.sh: could not parse the hook payload ({exc})', file=sys.stderr)
    pass
")

# --- Example: log every Write/Edit/NotebookEdit -------------------------------
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
    print(f'pretooluse.sh: could not parse the hook payload ({exc})', file=sys.stderr)
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
# Uncomment + customize if you want sandbox enforcement. Note `exit 2`: that's
# the code that blocks. File paths arrive absolute, with the platform's native
# separators (backslashes on Windows), so adjust the pattern there.
#
# case "$TOOL_NAME" in
#     Write|Edit)
#         FILE_PATH=$(printf '%s' "$PAYLOAD" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))")
#         case "$FILE_PATH" in
#             "$HOME/Projects/"*)
#                 ;;  # allowed
#             *)
#                 echo "Blocked by PreToolUse hook: writes outside ~/Projects/ are not allowed ($FILE_PATH)" >&2
#                 exit 2
#                 ;;
#         esac
#         ;;
# esac

exit 0
