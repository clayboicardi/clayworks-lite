#!/usr/bin/env bash
# =============================================================================
# SessionStart hook — customized example (from hooks/examples/sessionstart.sh)
# =============================================================================
# Two effects when a session opens:
#   1. If ~/agent/session-primer.md exists and is < 7 days old, I print it so it
#      lands in Claude's context (startup, /clear, and forked sessions only).
#   2. If the cwd is a git repo, I print a one-line warning when there's
#      uncommitted state (every source except resume).
#
# I get plain stdout into Claude's context; I rely on Claude Code wrapping it
# itself, so I print plain text rather than hand-rolled <system-reminder> tags.
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

PAYLOAD=$(cat)
# I join source + cwd with the ASCII unit separator (0x1f) so an empty field
# doesn't shift the other one.
FIELDS=$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('source', ''), d.get('cwd', ''), sep='\x1f', end='')
except Exception as exc:
    print(f'sessionstart.sh: I could not parse the hook payload ({exc})', file=sys.stderr)
    print('', '', sep='\x1f', end='')
")
IFS=$'\x1f' read -r SOURCE CWD <<< "$FIELDS"

# resume: I already have last time's primer in the conversation. compact: I
# keep the conversation going, so I skip the primer but keep the git warning.
case "$SOURCE" in
    resume)  SHOW_PRIMER=0; SHOW_GIT=0 ;;
    compact) SHOW_PRIMER=0; SHOW_GIT=1 ;;
    *)       SHOW_PRIMER=1; SHOW_GIT=1 ;;
esac

# --- Primer file injection ---------------------------------------------------
# SECURITY: I land anything printed here in Claude's context as trusted hook
# output, so I treat $PRIMER's path as security-sensitive — chmod 600.

PRIMER="$HOME/agent/session-primer.md"

if [[ "$SHOW_PRIMER" -eq 1 && -f "$PRIMER" ]]; then
    PRIMER_MTIME=$(python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$PRIMER" 2>/dev/null || echo 0)
    AGE_DAYS=$(( ( $(date +%s) - PRIMER_MTIME ) / 86400 ))
    if [[ "$AGE_DAYS" -lt 7 ]]; then
        printf 'Session primer (%sd old):\n' "$AGE_DAYS"
        cat "$PRIMER"
        printf '\n'
    fi
fi

# --- Uncommitted-git warning -------------------------------------------------

if [[ "$SHOW_GIT" -eq 1 && -n "$CWD" && -d "$CWD/.git" ]]; then
    UNCOMMITTED=$(GIT_OPTIONAL_LOCKS=0 git -C "$CWD" \
        -c core.fsmonitor=false \
        -c core.hooksPath=/dev/null \
        status --porcelain 2>/dev/null | wc -l)
    if [[ "$UNCOMMITTED" -gt 0 ]]; then
        printf 'Git state: in %s I see %d uncommitted change(s).\n' "$CWD" "$UNCOMMITTED"
    fi
fi

exit 0
