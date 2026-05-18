#!/usr/bin/env bash
# =============================================================================
# PreToolUse hook — fires BEFORE a tool call executes
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "tool_name": "Bash" | "Edit" | "Write" | ...,
#     "tool_input": { ... },     # the arguments Claude is about to pass
#     "session_id": "...",
#     "cwd": "/path/to/cwd"
#   }
#
# Common uses:
#   - Sandbox enforcement (block Write/Edit outside a specific dir)
#   - Audit logging (record every tool call with timestamp)
#   - Confirmation prompts (interactive — beware of CC's --headless modes)
#   - Resource guards (block expensive operations during low-budget time)
#
# Exit behavior:
#   - Exit 0  → tool call proceeds normally
#   - Exit !=0 → tool call is BLOCKED (some CC versions); stderr surfaces as error
#   - stdout is typically suppressed (some hooks log it)
#
# IMPORTANT: PreToolUse hooks fire on EVERY tool call. Keep them FAST (<100ms
# ideal). A slow hook adds latency to every interaction.
#
# Register in ~/.claude/settings.json under hooks.PreToolUse with a matcher:
#   { "matcher": "Write|Edit|MultiEdit", "hooks": [{...}] }
# =============================================================================

set -u

PAYLOAD=$(cat)
TOOL_NAME=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_name', ''), end='')
except Exception:
    pass
")

# --- Example: log every Write/Edit/MultiEdit ----------------------------------
# Useful for auditing what Claude touched. Replace with your own logic.

LOG_DIR="$HOME/agent/logs"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/tool-audit.log"

case "$TOOL_NAME" in
    Write|Edit|MultiEdit|NotebookEdit)
        TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        FILE_PATH=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', '<unknown>'), end='')
except Exception:
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
# Uncomment + customize if you want sandbox enforcement.
#
# case "$TOOL_NAME" in
#     Write|Edit|MultiEdit)
#         FILE_PATH=$(printf '%s' "$PAYLOAD" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))")
#         case "$FILE_PATH" in
#             "$HOME/Projects/"*)
#                 ;;  # allowed
#             *)
#                 echo "PreToolUse hook: write outside ~/Projects/ blocked ($FILE_PATH)" >&2
#                 exit 1
#                 ;;
#         esac
#         ;;
# esac

exit 0
