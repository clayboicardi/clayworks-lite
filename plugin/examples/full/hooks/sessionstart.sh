#!/usr/bin/env bash
# =============================================================================
# SessionStart hook — customized example (from hooks/examples/sessionstart.sh)
# =============================================================================
# Two effects on each session open:
#   1. If ~/agent/session-primer.md exists and is < 7 days old, inject it as
#      a <session-primer> system-reminder.
#   2. If the cwd is a git repo, surface a one-line warning when there's
#      uncommitted state.
#
# Notes:
#   - Primer file is a confused-deputy injection channel — chmod 600 it
#     (see comment block below).
#   - git status uses -c core.fsmonitor=false / -c core.hooksPath=/dev/null
#     to neutralize CVE-2022-39253-class config-based execution vectors when
#     opening CC inside an untrusted repo. Hook-based vectors in .git/hooks/
#     are NOT fully covered by this guard.
# =============================================================================

set -u

# --- Primer file injection ---------------------------------------------------
# SECURITY: anything printed here is injected into the session as a trusted
# system-reminder. Treat $PRIMER's path as security-sensitive — chmod 600.

PRIMER="$HOME/agent/session-primer.md"

if [[ -f "$PRIMER" ]]; then
    PRIMER_MTIME=$(python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$PRIMER" 2>/dev/null || echo 0)
    AGE_DAYS=$(( ( $(date +%s) - PRIMER_MTIME ) / 86400 ))
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

# --- Uncommitted-git warning -------------------------------------------------

PAYLOAD=$(cat)
CWD=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('cwd', ''), end='')
except Exception:
    pass
")

if [[ -d "$CWD/.git" ]]; then
    UNCOMMITTED=$(GIT_OPTIONAL_LOCKS=0 git -C "$CWD" \
        -c core.fsmonitor=false \
        -c core.hooksPath=/dev/null \
        status --porcelain 2>/dev/null | wc -l)
    if [[ "$UNCOMMITTED" -gt 0 ]]; then
        printf '<git-warning>%s has %d uncommitted change(s).</git-warning>\n' "$CWD" "$UNCOMMITTED"
    fi
fi

exit 0
