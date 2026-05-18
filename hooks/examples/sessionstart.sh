#!/usr/bin/env bash
# =============================================================================
# SessionStart hook — fires when a Claude Code session begins
# =============================================================================
# Payload (stdin, JSON):
#   {
#     "session_id": "...",
#     "cwd": "/path/to/cwd",
#     "model": "claude-opus-4-7",
#     "started_at": "ISO-8601 timestamp"
#   }
#
# Common uses:
#   - Surface a primer file ("here's what you were working on last time")
#   - Inject project-specific context if cwd matches a known project
#   - Warn about uncommitted state, stale branches, etc.
#   - Log session-start telemetry
#
# Exit behavior: stdout is injected as a <system-reminder> at session start.
# Non-zero exit logs the failure but doesn't block the session.
#
# Register in ~/.claude/settings.json under hooks.SessionStart.
# =============================================================================

set -u

# --- Example: surface a primer file if it exists -----------------------------
# Convention: ~/agent/session-primer.md contains "what's most urgent right now"
# Maintained by your evening consolidation, weekly review, or written ad-hoc.

PRIMER="$HOME/agent/session-primer.md"

if [[ -f "$PRIMER" ]]; then
    # Check the file is recent (< 7 days) before surfacing — otherwise it's stale.
    AGE_DAYS=$(( ( $(date +%s) - $(date -r "$PRIMER" +%s) ) / 86400 ))
    if [[ "$AGE_DAYS" -lt 7 ]]; then
        cat <<EOF
<session-primer freshness="${AGE_DAYS}d-old">
EOF
        cat "$PRIMER"
        cat <<'EOF'
</session-primer>
EOF
    fi
fi

# --- Example: warn about uncommitted git state in cwd ------------------------
PAYLOAD=$(cat)
CWD=$(printf '%s' "$PAYLOAD" | python -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('cwd', ''), end='')
except Exception:
    pass
")

if [[ -d "$CWD/.git" ]]; then
    UNCOMMITTED=$(cd "$CWD" && git status --porcelain 2>/dev/null | wc -l)
    if [[ "$UNCOMMITTED" -gt 0 ]]; then
        printf '<git-warning>%s has %d uncommitted change(s) at session start.</git-warning>\n' "$CWD" "$UNCOMMITTED"
    fi
fi

exit 0
