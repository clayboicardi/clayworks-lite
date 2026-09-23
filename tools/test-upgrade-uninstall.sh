#!/usr/bin/env bash
# Upgrade-uninstall test: install an older LITE release with ITS install.sh,
# use it like a 1.0.x user would, then uninstall with the current install.sh.
#
# I check that every untouched artifact goes away, the legacy Nudge DB moves
# to its stable home first, and anything you edited or added stays put.
#
# Usage: tools/test-upgrade-uninstall.sh [old-ref]   (default: v1.0.1)
# Needs the old ref in local history (CI: actions/checkout fetch-depth: 0).

set -euo pipefail

OLD_REF="${1:-v1.0.1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
OLD_TREE="${WORK}/old"

cleanup() {
    git -C "$REPO_ROOT" worktree remove --force "$OLD_TREE" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

# The test asserts the default DB location, so an override would break it.
unset CLAYWORKS_NUDGE_DB

git -C "$REPO_ROOT" worktree add --detach "$OLD_TREE" "$OLD_REF" >/dev/null

FAILS=0
fail() { echo "FAIL: $1" >&2; FAILS=$((FAILS+1)); }
want_gone()    { [[ ! -e "$1" ]] || fail "still present: $1"; }
want_present() { [[ -e "$1" ]]   || fail "missing: $1"; }

old_install() {
    bash "${OLD_TREE}/install.sh" --claude-dir "$1" >/dev/null
}

# Scenario A: a 1.0.x user ran Nudge (DB + __pycache__ in the skill dir) and
# edited one hook example. Everything else must go; the edit must stay.
A="${WORK}/claude-a"
old_install "$A"
nudge_scripts="${A}/skills/clayworks-lite-nudge/scripts"
printf 'legacy-db-bytes\n' > "${nudge_scripts}/alerts.db"
mkdir -p "${nudge_scripts}/__pycache__"
printf 'x' > "${nudge_scripts}/__pycache__/x.pyc"
printf '# my edit\n' >> "${A}/hooks/examples/stop.sh"

out_a="$(bash "${REPO_ROOT}/install.sh" --uninstall --claude-dir "$A")"
echo "$out_a"
for s in clayworks-lite-nudge clayworks-lite-memory-routing clayworks-lite-heartbeat-concept; do
    want_gone "${A}/skills/${s}"
done
want_gone "${A}/CLAUDE.md.clayworks-template"
want_gone "${A}/settings.example.json"
want_present "${A}/hooks/examples/stop.sh"
grep -q '^# my edit$' "${A}/hooks/examples/stop.sh" || fail "user edit to stop.sh lost"
[[ "$(cat "${A}/clayworks-lite/nudge/alerts.db" 2>/dev/null)" == "legacy-db-bytes" ]] \
    || fail "legacy alerts.db did not move to ${A}/clayworks-lite/nudge/alerts.db"
grep -q "Uninstall finished; 1 item(s) kept" <<< "$out_a" || fail "scenario A: wrong closing line"

# Scenario B: a file you added to a skill, and a legacy DB that can't move
# because the stable DB already exists. Both dirs must stay.
B="${WORK}/claude-b"
old_install "$B"
printf 'mine\n' > "${B}/skills/clayworks-lite-memory-routing/my-notes.md"
printf 'legacy\n' > "${B}/skills/clayworks-lite-nudge/scripts/alerts.db"
mkdir -p "${B}/clayworks-lite/nudge"
printf 'stable\n' > "${B}/clayworks-lite/nudge/alerts.db"

out_b="$(bash "${REPO_ROOT}/install.sh" --uninstall --claude-dir "$B")"
echo "$out_b"
want_present "${B}/skills/clayworks-lite-memory-routing/my-notes.md"
want_present "${B}/skills/clayworks-lite-nudge/scripts/alerts.db"
want_gone "${B}/skills/clayworks-lite-heartbeat-concept"
want_gone "${B}/hooks/examples"
[[ "$(cat "${B}/clayworks-lite/nudge/alerts.db")" == "stable" ]] || fail "stable DB was overwritten"
grep -q "Uninstall finished; 2 item(s) kept" <<< "$out_b" || fail "scenario B: wrong closing line"

# Scenario C: CLAYWORKS_NUDGE_DB points into an existing shared dir. The move
# must not tighten that dir's permissions. (Git Bash ignores chmod, so this
# only bites on macOS / Linux.)
C="${WORK}/claude-c"
shared="${WORK}/shared"
old_install "$C"
printf 'legacy\n' > "${C}/skills/clayworks-lite-nudge/scripts/alerts.db"
mkdir -p "$shared"
chmod 755 "$shared"
CLAYWORKS_NUDGE_DB="${shared}/alerts.db" bash "${REPO_ROOT}/install.sh" --uninstall --claude-dir "$C" >/dev/null
[[ "$(cat "${shared}/alerts.db" 2>/dev/null)" == "legacy" ]] || fail "DB did not move to CLAYWORKS_NUDGE_DB"
[[ -n "$(find "$shared" -maxdepth 0 -perm 755)" ]] || fail "installer changed the shared dir's permissions"
want_gone "${C}/skills/clayworks-lite-nudge"

if [[ $FAILS -gt 0 ]]; then
    echo "upgrade-uninstall from ${OLD_REF}: ${FAILS} failure(s)" >&2
    exit 1
fi
echo "OK: upgrade-uninstall from ${OLD_REF} passed"
