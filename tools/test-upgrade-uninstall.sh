#!/usr/bin/env bash
# Upgrade and uninstall tests for install.sh against an older LITE release:
# I install that release with ITS install.sh, use it like a 1.0.x user would,
# then run the current install.sh over it.
#
# I check that every untouched artifact goes away, that a legacy Nudge DB
# lands in nudge-import/ (where the runtime merges it) instead of in a
# backup or the bin, and that anything you edited or added stays put.
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

# Most scenarios assert the default DB location, so an override would break
# them. The override scenario at the end sets its own.
unset CLAYWORKS_NUDGE_DB

git -C "$REPO_ROOT" worktree add --detach "$OLD_TREE" "$OLD_REF" >/dev/null

FAILS=0
fail() { echo "FAIL: $1" >&2; FAILS=$((FAILS+1)); }
want_gone()    { [[ ! -e "$1" ]] || fail "still present: $1"; }
want_present() { [[ -e "$1" ]]   || fail "missing: $1"; }

old_install() { bash "${OLD_TREE}/install.sh" --claude-dir "$1" >/dev/null; }
new_install() { bash "${REPO_ROOT}/install.sh" --claude-dir "$1"; }
new_uninstall() { bash "${REPO_ROOT}/install.sh" --uninstall --claude-dir "$1"; }

# The shell-quoted form install.sh prints in its purge commands.
q() { printf '%q' "$1"; }

# Print the content of the single legacy-*.db in a nudge-import dir, or fail.
imported_content() {
    local dir="$1" found=()
    local f
    for f in "$dir"/legacy-*.db; do
        [[ -f "$f" ]] && found+=("$f")
    done
    if [[ ${#found[@]} -ne 1 ]]; then
        fail "expected exactly one legacy-*.db in ${dir}, found ${#found[@]}"
        return 0
    fi
    cat "${found[0]}"
}

# (a) + (e) A 1.0.x user ran Nudge (DB + __pycache__ in the skill dir) and
# edited one hook example. Uninstall removes everything else, hands the DB to
# nudge-import/, and names this root in the purge instructions.
A="${WORK}/claude-a"
old_install "$A"
nudge_scripts="${A}/skills/clayworks-lite-nudge/scripts"
printf 'legacy-db-bytes\n' > "${nudge_scripts}/alerts.db"
mkdir -p "${nudge_scripts}/__pycache__"
printf 'x' > "${nudge_scripts}/__pycache__/x.pyc"
printf '# my edit\n' >> "${A}/hooks/examples/stop.sh"

out_a="$(new_uninstall "$A")"
echo "$out_a"
for s in clayworks-lite-nudge clayworks-lite-memory-routing clayworks-lite-heartbeat-concept; do
    want_gone "${A}/skills/${s}"
done
want_gone "${A}/CLAUDE.md.clayworks-template"
want_gone "${A}/settings.example.json"
want_present "${A}/hooks/examples/stop.sh"
grep -q '^# my edit$' "${A}/hooks/examples/stop.sh" || fail "user edit to stop.sh lost"
[[ "$(imported_content "${A}/clayworks-lite/nudge/nudge-import")" == "legacy-db-bytes" ]] \
    || fail "(a) legacy DB did not land in ${A}/clayworks-lite/nudge/nudge-import"
grep -q "Uninstall finished; 1 item(s) kept" <<< "$out_a" || fail "(a) wrong closing line"
grep -qxF "  rm -rf $(q "${A}/.clayworks-lite-backup")" <<< "$out_a" || fail "(e) purge text lacks this root's backup dir"
grep -qxF "  rm -rf $(q "${A}/clayworks-lite")" <<< "$out_a" || fail "(e) purge text lacks this root's clayworks-lite dir"
if grep -q '[~]/[.]claude' <<< "$out_a"; then fail "(e) uninstall output still names ~/.claude"; fi

# (b) You customized the Nudge skill and added a file to another skill. Both
# stay, and alerts.db stays inside the kept Nudge dir for its 1.0.x scripts.
B="${WORK}/claude-b"
old_install "$B"
printf 'mine\n' > "${B}/skills/clayworks-lite-memory-routing/my-notes.md"
printf '# my tweak\n' >> "${B}/skills/clayworks-lite-nudge/SKILL.md"
printf 'legacy\n' > "${B}/skills/clayworks-lite-nudge/scripts/alerts.db"

out_b="$(new_uninstall "$B")"
echo "$out_b"
want_present "${B}/skills/clayworks-lite-memory-routing/my-notes.md"
[[ "$(cat "${B}/skills/clayworks-lite-nudge/scripts/alerts.db" 2>/dev/null)" == "legacy" ]] \
    || fail "(b) alerts.db left the kept Nudge skill"
want_gone "${B}/clayworks-lite/nudge/nudge-import"
want_gone "${B}/skills/clayworks-lite-heartbeat-concept"
want_gone "${B}/hooks/examples"
grep -q "Uninstall finished; 2 item(s) kept" <<< "$out_b" || fail "(b) wrong closing line"

# A custom.pyc beside a skill's SKILL.md is yours, so that skill stays; a
# .pyc inside __pycache__/ is Python's, so it doesn't hold its skill back.
P="${WORK}/claude-p"
old_install "$P"
printf 'mine' > "${P}/skills/clayworks-lite-memory-routing/custom.pyc"
mkdir -p "${P}/skills/clayworks-lite-heartbeat-concept/__pycache__"
printf 'x' > "${P}/skills/clayworks-lite-heartbeat-concept/__pycache__/x.pyc"
out_p="$(new_uninstall "$P")"
want_present "${P}/skills/clayworks-lite-memory-routing/custom.pyc"
want_gone "${P}/skills/clayworks-lite-heartbeat-concept"
grep -q "skill: clayworks-lite-memory-routing: customized" <<< "$out_p" \
    || fail "(pyc) custom.pyc beside SKILL.md did not mark the skill customized"

# (c) A fresh install creates the Nudge dir the runtime uses as its marker.
C="${WORK}/claude-c"
out_c="$(new_install "$C")"
[[ -d "${C}/clayworks-lite/nudge" ]] || fail "(c) fresh install did not create ${C}/clayworks-lite/nudge"
# Its next steps name this root, shell-quoted, not ~/.claude.
grep -qF "$(q "$C")/settings.example.json to $(q "$C")/settings.json" <<< "$out_c" \
    || fail "(c) next steps do not name this root"
if grep -q '[~]/[.]claude' <<< "$out_c"; then fail "(c) next steps still name ~/.claude"; fi

# A symlinked (or, on Windows, junctioned) clayworks-lite/nudge that points
# outside the root: install and uninstall must both refuse before writing
# anything, and nothing may land outside the root.
# Link $2 to dir $1: a junction on Git Bash (no admin needed), else a symlink.
make_link() {
    case "${OSTYPE:-}" in
        msys*|cygwin*) cmd //c mklink //J "$(cygpath -w "$2")" "$(cygpath -w "$1")" >/dev/null ;;
        *) ln -s "$1" "$2" ;;
    esac
    [[ -L "$2" ]] || fail "could not create a symlink or junction at $2"
}

# Run install and uninstall against root $1; both must refuse with exit 5.
want_refused() {
    local root="$1" label="$2" rc
    rc=0
    new_install "$root" >/dev/null 2>&1 || rc=$?
    [[ $rc -eq 5 ]] || fail "(${label}) install did not refuse (exit ${rc})"
    rc=0
    new_uninstall "$root" >/dev/null 2>&1 || rc=$?
    [[ $rc -eq 5 ]] || fail "(${label}) uninstall did not refuse (exit ${rc})"
}

L="${WORK}/claude-l"
outside="${WORK}/outside"
mkdir -p "${L}/clayworks-lite" "$outside"
make_link "$outside" "${L}/clayworks-lite/nudge"
want_refused "$L" "symlinked nudge dir"
[[ -z "$(ls -A "$outside")" ]] || fail "(symlinked nudge dir) the installer wrote outside the root"
want_gone "${L}/skills"

# A symlinked (or junctioned) Nudge skill dir, and separately a symlinked
# skills/, pointing at an unrelated folder that holds scripts/alerts.db:
# install and uninstall must both refuse, and that DB must stay untouched.
ext="${WORK}/external-skill"
mkdir -p "${ext}/scripts"
printf 'external-db\n' > "${ext}/scripts/alerts.db"
M="${WORK}/claude-m"
mkdir -p "${M}/skills"
make_link "$ext" "${M}/skills/clayworks-lite-nudge"
want_refused "$M" "symlinked skill dir"
ext_skills="${WORK}/external-skills"
mkdir -p "$ext_skills"
make_link "$ext" "${ext_skills}/clayworks-lite-nudge"
N="${WORK}/claude-n"
mkdir -p "$N"
make_link "$ext_skills" "${N}/skills"
want_refused "$N" "symlinked skills dir"
[[ "$(cat "${ext}/scripts/alerts.db" 2>/dev/null)" == "external-db" ]] \
    || fail "(symlinked skill dir) the external alerts.db was moved or changed"
[[ "$(ls -A "$ext")" == "scripts" && "$(ls -A "${ext}/scripts")" == "alerts.db" ]] \
    || fail "(symlinked skill dir) the installer changed the external folder"

# A symlinked hooks/ pointing at an external dir that holds examples/: install
# and uninstall must both refuse, and the external dir must stay intact.
ext_hooks="${WORK}/external-hooks"
mkdir -p "${ext_hooks}/examples"
printf 'theirs\n' > "${ext_hooks}/examples/stop.sh"
Q="${WORK}/claude-q"
mkdir -p "$Q"
make_link "$ext_hooks" "${Q}/hooks"
want_refused "$Q" "symlinked hooks dir"
[[ "$(cat "${ext_hooks}/examples/stop.sh" 2>/dev/null)" == "theirs" && "$(ls -A "${ext_hooks}/examples")" == "stop.sh" ]] \
    || fail "(symlinked hooks dir) the external examples/ changed"
want_gone "${Q}/skills"

# A symlink you added inside an otherwise unchanged skill: uninstall keeps
# that skill (and your link) and removes the rest.
R="${WORK}/claude-r"
new_install "$R" >/dev/null
link_target="${WORK}/link-target"
mkdir -p "$link_target"
make_link "$link_target" "${R}/skills/clayworks-lite-memory-routing/mine-link"
out_r="$(new_uninstall "$R")"
[[ -L "${R}/skills/clayworks-lite-memory-routing/mine-link" ]] || fail "(inner symlink) your link was removed"
want_present "${R}/skills/clayworks-lite-memory-routing/SKILL.md"
want_gone "${R}/skills/clayworks-lite-heartbeat-concept"
grep -q "skill: clayworks-lite-memory-routing: customized" <<< "$out_r" \
    || fail "(inner symlink) the skill holding your link was not kept as customized"

# CLAYWORKS_NUDGE_DB inside another LITE skill, which install replaces and
# uninstall removes: both must refuse with exit 2, and the store must stay
# put with its row.
S="${WORK}/claude-s"
new_install "$S" >/dev/null
store_s="${S}/skills/clayworks-lite-memory-routing/custom.db"
printf 'row-s\n' > "$store_s"
for mode in install uninstall; do
    rc=0
    if [[ $mode == install ]]; then
        out_s="$(CLAYWORKS_NUDGE_DB="$store_s" new_install "$S" 2>&1)" || rc=$?
    else
        out_s="$(CLAYWORKS_NUDGE_DB="$store_s" new_uninstall "$S" 2>&1)" || rc=$?
    fi
    [[ $rc -eq 2 ]] || fail "(db in managed skill) ${mode} did not refuse (exit ${rc})"
    grep -q "CLAYWORKS_NUDGE_DB points inside" <<< "$out_s" || fail "(db in managed skill) ${mode} gave no error"
done
[[ "$(cat "$store_s" 2>/dev/null)" == "row-s" ]] || fail "(db in managed skill) the store moved or changed"
if [[ -n "$(find "${S}/.clayworks-lite-backup" -name custom.db 2>/dev/null)" ]]; then
    fail "(db in managed skill) the store was backed up, so install replaced its skill"
fi

# A symlinked install root itself is fine (dotfile setups): install and
# uninstall through it work as usual.
real_root="${WORK}/real-root"
mkdir -p "$real_root"
make_link "$real_root" "${WORK}/linked-root"
new_install "${WORK}/linked-root" >/dev/null || fail "(symlinked root) install refused a symlinked root"
[[ -f "${real_root}/skills/clayworks-lite-nudge/SKILL.md" ]] || fail "(symlinked root) skills missing"
new_uninstall "${WORK}/linked-root" >/dev/null || fail "(symlinked root) uninstall refused a symlinked root"

# (d) An install over a 1.0.x skill whose stable DB already exists: the
# legacy DB lands in nudge-import/, not in the backup, and the stable DB is intact.
D="${WORK}/claude-d"
old_install "$D"
printf 'legacy-d\n' > "${D}/skills/clayworks-lite-nudge/scripts/alerts.db"
mkdir -p "${D}/clayworks-lite/nudge"
printf 'stable\n' > "${D}/clayworks-lite/nudge/alerts.db"
new_install "$D" >/dev/null
[[ "$(imported_content "${D}/clayworks-lite/nudge/nudge-import")" == "legacy-d" ]] \
    || fail "(d) legacy DB did not land in nudge-import/"
[[ "$(cat "${D}/clayworks-lite/nudge/alerts.db")" == "stable" ]] || fail "(d) stable DB changed"
if [[ -n "$(find "${D}/.clayworks-lite-backup" -name alerts.db 2>/dev/null)" ]]; then
    fail "(d) legacy DB ended up in the backup folder"
fi

# CLAYWORKS_NUDGE_DB points into an existing shared dir. The nudge-import dir goes
# next to that DB, the shared dir keeps its permissions (Git Bash ignores
# chmod, so that part only bites on macOS / Linux), and the purge text names
# only Nudge's own files there.
F="${WORK}/claude-f"
shared="${WORK}/shared"
old_install "$F"
printf 'legacy-f\n' > "${F}/skills/clayworks-lite-nudge/scripts/alerts.db"
mkdir -p "$shared"
chmod 755 "$shared"
out_f="$(CLAYWORKS_NUDGE_DB="${shared}/alerts.db" new_uninstall "$F")"
[[ "$(imported_content "${shared}/nudge-import")" == "legacy-f" ]] || fail "(override) legacy DB not in ${shared}/nudge-import"
[[ -n "$(find "$shared" -maxdepth 0 -perm 755)" ]] || fail "(override) installer changed the shared dir's permissions"
want_gone "${F}/skills/clayworks-lite-nudge"
grep -qxF "  rm -f $(q "${shared}/alerts.db")" <<< "$out_f" || fail "(override) purge text lacks the DB file"
grep -qxF "  rm -rf $(q "${shared}/nudge-import")" <<< "$out_f" || fail "(override) purge text lacks the nudge-import dir"
for bad in "$shared" "${shared}/import"; do
    if grep -qxF "  rm -rf $(q "$bad")" <<< "$out_f"; then
        fail "(override) purge text names the shared dir or a generic import/"
    fi
done

# CLAYWORKS_NUDGE_DB points at the 1.0.x DB inside the skill dir itself. The
# nudge-import dir next to it would go down with the skill dir, so both
# uninstall and install-over must fall back to <root>/clayworks-lite/nudge/
# and warn, and the alerts must survive there.
G="${WORK}/claude-g"
old_install "$G"
printf 'legacy-g\n' > "${G}/skills/clayworks-lite-nudge/scripts/alerts.db"
out_g="$(CLAYWORKS_NUDGE_DB="${G}/skills/clayworks-lite-nudge/scripts/alerts.db" new_uninstall "$G")"
want_gone "${G}/skills/clayworks-lite-nudge"
[[ "$(imported_content "${G}/clayworks-lite/nudge/nudge-import")" == "legacy-g" ]] \
    || fail "(db-in-skill uninstall) alerts lost"
grep -q "WARNING: CLAYWORKS_NUDGE_DB" <<< "$out_g" || fail "(db-in-skill uninstall) no warning"

H="${WORK}/claude-h"
old_install "$H"
printf 'legacy-h\n' > "${H}/skills/clayworks-lite-nudge/scripts/alerts.db"
out_h="$(CLAYWORKS_NUDGE_DB="${H}/skills/clayworks-lite-nudge/scripts/alerts.db" new_install "$H")"
[[ "$(imported_content "${H}/clayworks-lite/nudge/nudge-import")" == "legacy-h" ]] \
    || fail "(db-in-skill install) alerts lost"
want_gone "${H}/skills/clayworks-lite-nudge/scripts/nudge-import"
grep -q "WARNING: CLAYWORKS_NUDGE_DB" <<< "$out_h" || fail "(db-in-skill install) no warning"

# CLAYWORKS_NUDGE_DB names some other file inside the skill dir, with a WAL
# sidecar. Install-over and uninstall must both hand that store (and its
# sidecar) to the fallback nudge-import/ before the skill dir goes, and keep
# it out of the backup.
I="${WORK}/claude-i"
old_install "$I"
printf 'custom-i\n' > "${I}/skills/clayworks-lite-nudge/scripts/custom.db"
printf 'wal-i\n' > "${I}/skills/clayworks-lite-nudge/scripts/custom.db-wal"
printf 'journal-i\n' > "${I}/skills/clayworks-lite-nudge/scripts/custom.db-journal"
out_i="$(CLAYWORKS_NUDGE_DB="${I}/skills/clayworks-lite-nudge/scripts/custom.db" new_install "$I")"
[[ "$(imported_content "${I}/clayworks-lite/nudge/nudge-import")" == "custom-i" ]] \
    || fail "(custom-db install) store lost"
[[ "$(cat "${I}"/clayworks-lite/nudge/nudge-import/legacy-*.db-wal 2>/dev/null)" == "wal-i" ]] \
    || fail "(custom-db install) WAL sidecar lost"
[[ "$(cat "${I}"/clayworks-lite/nudge/nudge-import/legacy-*.db-journal 2>/dev/null)" == "journal-i" ]] \
    || fail "(custom-db install) rollback journal did not move with the store"
if [[ -n "$(find "${I}/.clayworks-lite-backup" -name 'custom.db*' 2>/dev/null)" ]]; then
    fail "(custom-db install) store ended up in the backup folder"
fi
grep -q "WARNING: CLAYWORKS_NUDGE_DB" <<< "$out_i" || fail "(custom-db install) no warning"

J="${WORK}/claude-j"
old_install "$J"
printf 'custom-j\n' > "${J}/skills/clayworks-lite-nudge/scripts/custom.db"
out_j="$(CLAYWORKS_NUDGE_DB="${J}/skills/clayworks-lite-nudge/scripts/custom.db" new_uninstall "$J")"
want_gone "${J}/skills/clayworks-lite-nudge"
[[ "$(imported_content "${J}/clayworks-lite/nudge/nudge-import")" == "custom-j" ]] \
    || fail "(custom-db uninstall) store lost"
grep -q "WARNING: CLAYWORKS_NUDGE_DB" <<< "$out_j" || fail "(custom-db uninstall) no warning"

# A claude dir with an apostrophe and a space. Each printed purge command,
# run through bash with rm swapped for a recorder, must name the right path.
K="${WORK}/O'Brien root"
new_install "$K" >/dev/null
out_k="$(new_uninstall "$K")"
for want in "${K}/.clayworks-lite-backup" "${K}/clayworks-lite"; do
    line="$(grep -xF "  rm -rf $(q "$want")" <<< "$out_k" || true)"
    if [[ -z "$line" ]]; then
        fail "(quoting) no purge line for ${want}"
        continue
    fi
    got="$(bash -c 'rm() { printf "%s\n" "$2"; }; eval "$1"' _ "$line")"
    [[ "$got" == "$want" ]] || fail "(quoting) purge line targets '${got}', not '${want}'"
done

if [[ $FAILS -gt 0 ]]; then
    echo "upgrade tests from ${OLD_REF}: ${FAILS} failure(s)" >&2
    exit 1
fi
echo "OK: upgrade tests from ${OLD_REF} passed"
