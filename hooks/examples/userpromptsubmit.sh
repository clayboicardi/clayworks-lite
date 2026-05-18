#!/usr/bin/env bash
# =============================================================================
# UserPromptSubmit hook — fires on every prompt the user sends
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "prompt": "...",           # the user's prompt text
#     "session_id": "...",       # UUID for this CC session
#     "cwd": "/path/to/cwd",     # working directory
#     "transcript_path": "...",  # path to session transcript JSONL
#     "model": "claude-opus-4-7" # active model ID
#   }
#
# Common uses:
#   - Inject reminders that should reach Claude this turn (e.g., due nudges)
#   - Detect prompt keywords and inject relevant context (freshness gates)
#   - Log prompts for later analysis (with care for privacy)
#   - Surface time-sensitive state (active hours, pending PRs, etc.)
#
# Exit behavior:
#   - stdout is injected into the session as a <system-reminder> block
#   - non-zero exit logs the failure but does NOT block the prompt
#
# Register in ~/.claude/settings.json under hooks.UserPromptSubmit.
# =============================================================================

set -u

# Parse the prompt from stdin payload.
PAYLOAD=$(cat)
PROMPT=$(printf '%s' "$PAYLOAD" | python -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', ''), end='')
except Exception:
    pass
")

# --- Example: surface keyword-triggered context -----------------------------
# Replace the keyword check + injected text with whatever you actually want.

PROMPT_LOWER=$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')

case "$PROMPT_LOWER" in
    *"deploy"*|*"release"*|*"production"*)
        cat <<'EOF'
<system-reminder>
Deployment-adjacent keyword detected in prompt. Reminder: verify CI is green,
double-check the target environment, and prefer staged rollouts over big-bang
releases. If this is just incidental mention, ignore this reminder.
</system-reminder>
EOF
        ;;
    *)
        # No match → no output → silent pass-through.
        ;;
esac

exit 0
