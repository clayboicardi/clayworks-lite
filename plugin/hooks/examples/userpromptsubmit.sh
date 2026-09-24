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
# (I see newer versions also send prompt_id. I get no model field on this event.)
#
# Common uses:
#   - Inject reminders that should reach Claude this turn (e.g., due nudges)
#   - Detect prompt keywords and inject relevant context (freshness gates)
#   - Log prompts for later analysis (with care for privacy)
#   - Surface time-sensitive state (active hours, pending PRs, etc.)
#
# Exit behavior:
#   - Exit 0 + plain-text stdout: I rely on Claude Code adding the text to
#     Claude's context next to the prompt and wrapping it itself (as a system
#     reminder that names the hook), so I print plain text, never tag-wrapped.
#   - I make sure stdout that starts with "{" is valid JSON output, or Claude
#     Code drops it and shows a hook error. I keep plain stdout within its
#     10,000-character cap.
#   - With exit 2 I BLOCK the prompt: Claude Code erases it and shows my stderr
#     to the user. I get only a non-blocking error notice from any other
#     non-zero exit.
#   - I know the default timeout on this event is 30s; I keep it far under that.
#
# I register it in ~/.claude/settings.json under hooks.UserPromptSubmit (no
# matcher; I get this event on every prompt).
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
    print(f'userpromptsubmit.sh: I could not parse the hook payload ({exc})', file=sys.stderr)
    pass
")

# --- Example: surface keyword-triggered context -----------------------------
# Replace the keyword check + injected text with whatever you actually want.
# I phrase injected text as plain facts or reminders. I've seen text styled as
# an out-of-band system command trip Claude's prompt-injection defenses.

PROMPT_LOWER=$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')

case "$PROMPT_LOWER" in
    *"deploy"*|*"release"*|*"production"*)
        cat <<'EOF'
I detected a deployment-adjacent keyword in the prompt. My checklist for this
kind of work: green CI, the intended target environment, and a staged rollout
over a big-bang release. If the mention is incidental, I'd ignore this.
EOF
        ;;
    *)
        # No match → no output → silent pass-through.
        ;;
esac

exit 0
