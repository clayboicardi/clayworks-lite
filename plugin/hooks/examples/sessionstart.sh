#!/usr/bin/env bash
# =============================================================================
# SessionStart hook — when a Claude Code session starts or resumes
# =============================================================================
# Payload (stdin, JSON), abridged from the Claude Code hooks reference:
#   {
#     "session_id": "abc123",
#     "transcript_path": "/Users/.../.claude/projects/.../<session>.jsonl",
#     "cwd": "/Users/.../my-project",
#     "hook_event_name": "SessionStart",
#     "source": "startup",
#     "model": "claude-opus-5-5"
#   }
# I get source as one of: startup | resume | clear | compact | fork
# I treat model as optional (Claude Code omits it after /clear, for example) and
# check for it before reading it. I can also get agent_type and session_title.
#
# Common uses:
#   - Surface a primer file ("here's what you were working on last time")
#   - Inject project-specific context if cwd matches a known project
#   - Warn about uncommitted state, stale branches, etc.
#   - Log session-start telemetry
#
# Exit behavior: I get plain-text stdout into Claude's context at the start of
# the conversation. I rely on Claude Code wrapping it itself, so I print plain
# text, never hand-wrapped in <system-reminder> tags. I can't block the session
# from SessionStart: with a non-zero exit I only show the user a hook-error notice.
#
# I register it in ~/.claude/settings.json under hooks.SessionStart. To run only
# on some sources, I'd use a matcher such as "startup|clear" instead of the
# in-script branch below.
# =============================================================================

set -u

PAYLOAD=$(cat)
# I extract both fields in one Python call, joined by the ASCII unit separator
# (0x1f). I picked it over a tab because it doesn't collapse when a field is
# empty.
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

# --- Branching on how the session started ------------------------------------
# startup / clear / fork : fresh context, so I surface the primer + git state.
# resume                 : I already have last time's primer in the conversation;
#                          I'd just duplicate context by re-injecting it.
# compact                : I keep the conversation going through compaction, so
#                          I skip the primer but still show the useful git warning.
case "$SOURCE" in
    resume)  SHOW_PRIMER=0; SHOW_GIT=0 ;;
    compact) SHOW_PRIMER=0; SHOW_GIT=1 ;;
    *)       SHOW_PRIMER=1; SHOW_GIT=1 ;;  # startup, clear, fork, or unknown
esac

# --- Example: surface a primer file if it exists -----------------------------
# Convention: ~/agent/session-primer.md contains "what's most urgent right now"
# Maintained by your evening consolidation, weekly review, or written ad-hoc.
#
# SECURITY: I land anything printed here in Claude's context as trusted hook
# output, so I treat $PRIMER as security-sensitive — any process that can write
# to that path can inject instructions into my next CC session (confused-deputy
# channel). The hardening I recommend:
#   - chmod 600 "$PRIMER" so only your user can write it
#   - keep it on a filesystem only your account can access
#   - if you sync your home dir across machines, audit who has write access

PRIMER="$HOME/agent/session-primer.md"

if [[ "$SHOW_PRIMER" -eq 1 && -f "$PRIMER" ]]; then
    # Check the file is recent (< 7 days) before surfacing — otherwise it's stale.
    # NOTE: `date -r` diverges between GNU and BSD/macOS — GNU reads the file's
    # mtime, BSD/macOS treats the arg as epoch seconds. Use Python for portability.
    PRIMER_MTIME=$(python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$PRIMER" 2>/dev/null || echo 0)
    AGE_DAYS=$(( ( $(date +%s) - PRIMER_MTIME ) / 86400 ))
    if [[ "$AGE_DAYS" -lt 7 ]]; then
        printf 'Session primer (%sd old, from %s):\n' "$AGE_DAYS" "$PRIMER"
        cat "$PRIMER"
        printf '\n'
    fi
fi

# --- Example: warn about uncommitted git state in cwd ------------------------
# SECURITY: invoking git in a user-controlled cwd is a foot-gun. A malicious
# .git/config in cwd can trigger arbitrary-command execution via core.fsmonitor,
# core.pager, alias.*, etc. (CVE-2022-39253 family). If your threat model
# includes "user might open CC inside an untrusted repo", either delete this
# block or guard further (cwd allowlist). The -c flags below neutralize the
# obvious config-based vectors; hook-based vectors in .git/hooks/ are NOT
# fully addressed by this guard and remain a residual risk.
if [[ "$SHOW_GIT" -eq 1 && -n "$CWD" && -d "$CWD/.git" ]]; then
    UNCOMMITTED=$(GIT_OPTIONAL_LOCKS=0 git -C "$CWD" \
        -c core.fsmonitor=false \
        -c core.hooksPath=/dev/null \
        status --porcelain 2>/dev/null | wc -l)
    if [[ "$UNCOMMITTED" -gt 0 ]]; then
        printf 'Git state: in %s I see %d uncommitted change(s) at session start.\n' "$CWD" "$UNCOMMITTED"
    fi
fi

exit 0
