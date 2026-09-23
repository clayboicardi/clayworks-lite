#!/usr/bin/env bash
# =============================================================================
# UserPromptSubmit hook — fires on every prompt the user sends
# =============================================================================
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "/Users/.../.claude/projects/.../<session>.jsonl",
#     "cwd": "/Users/.../my-project",
#     "permission_mode": "default",
#     "hook_event_name": "UserPromptSubmit",
#     "prompt": "Write a function to calculate the factorial of a number"
#   }
# (Newer versions also send prompt_id. There is no model field on this event.)
#
# Common uses:
#   - Inject reminders that should reach Claude this turn (e.g., due nudges)
#   - Detect prompt keywords and inject relevant context (freshness gates)
#   - Log prompts for later analysis (with care for privacy)
#   - Surface time-sensitive state (active hours, pending PRs, etc.)
#
# Exit behavior:
#   - Exit 0 + plain-text stdout: Claude Code adds the text to Claude's context
#     next to the prompt. Claude Code wraps it itself (as a system reminder
#     that names the hook), so print plain text; don't hand-wrap it in tags.
#   - Stdout that starts with "{" must be valid JSON output, or Claude Code
#     drops it and shows a hook error. Plain stdout caps at 10,000 characters.
#   - Exit 2 BLOCKS the prompt: Claude Code erases it and shows your stderr
#     to the user. Any other non-zero exit is a non-blocking error notice.
#   - Default timeout on this event is 30s; keep it far under that.
#
# Register in ~/.claude/settings.json under hooks.UserPromptSubmit (no matcher;
# this event fires on every prompt).
# =============================================================================

set -u

# Parse the prompt from stdin payload.
PAYLOAD=$(cat)
PROMPT=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', ''), end='')
except Exception as exc:
    print(f'userpromptsubmit.sh: could not parse the hook payload ({exc})', file=sys.stderr)
    pass
")

# --- Example: surface keyword-triggered context -----------------------------
# Replace the keyword check + injected text with whatever you actually want.
# Phrase injected text as plain facts or reminders. Text styled as an
# out-of-band system command can trip Claude's prompt-injection defenses.

PROMPT_LOWER=$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')

case "$PROMPT_LOWER" in
    *"deploy"*|*"release"*|*"production"*)
        cat <<'EOF'
Deployment-adjacent keyword detected in the prompt. Checklist for this kind of
work: CI is green, the target environment is the intended one, and a staged
rollout beats a big-bang release. If the mention is incidental, ignore this.
EOF
        ;;
    *)
        # No match → no output → silent pass-through.
        ;;
esac

exit 0
