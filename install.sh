#!/usr/bin/env bash
# Clayworks LITE installer - macOS / Linux / Git Bash on Windows
# https://github.com/clayboicardi/clayworks-lite
#
# Installs the Clayworks LITE components into ~/.claude/ without clobbering
# your existing setup. Any file the installer is about to overwrite is first
# copied to ~/.claude/.clayworks-lite-backup/<timestamp>/.
#
# Usage: ./install.sh [--dry-run] [--uninstall] [--verify] [--claude-dir PATH]

set -eo pipefail

# --- Argument parsing --------------------------------------------------------

DRY_RUN=0
UNINSTALL=0
VERIFY=0
CLAUDE_DIR="${HOME}/.claude"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=1; shift ;;
        --uninstall)  UNINSTALL=1; shift ;;
        --verify)     VERIFY=1; shift ;;
        --claude-dir) CLAUDE_DIR="$2"; shift 2 ;;
        -h|--help)
            cat <<EOF
Clayworks LITE installer

Usage: ./install.sh [OPTIONS]

Options:
  --dry-run            Show what would change without writing
  --uninstall          Remove LITE-shipped files (only the ones LITE installed);
                       skips items you've customized so your edits aren't lost
  --verify             Check the install — file presence, Python/sqlite3, etc.
  --claude-dir PATH    Install root (default: ~/.claude)
  -h, --help           Show this message

Installs:
  skills/clayworks-lite-*/      -> \$CLAUDE_DIR/skills/
  hooks/examples/               -> \$CLAUDE_DIR/hooks/examples/
  templates/CLAUDE.md.*         -> \$CLAUDE_DIR/CLAUDE.md.clayworks-template
  templates/settings.example.json -> \$CLAUDE_DIR/settings.example.json

Your live \$CLAUDE_DIR/CLAUDE.md, \$CLAUDE_DIR/settings.json, and
\$CLAUDE_DIR/hooks/ are never touched. Nudge alerts live in
\$CLAUDE_DIR/clayworks-lite/nudge/ and survive reinstall and uninstall.
Anything overwritten is first copied to \$CLAUDE_DIR/.clayworks-lite-backup/.
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# --- Paths -------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="${CLAUDE_DIR}/.clayworks-lite-backup"
# PID suffix protects against directory collision if two installers run in
# the same second (rare, but possible from CI matrices or scripted retries).
TIMESTAMP="$(date +%Y%m%d-%H%M%S)-$$"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

# Absolute, symlink-resolved form of a path that may not exist yet, for
# comparing paths. Git Bash on Windows compares case-insensitively, so there
# I lowercase it too.
norm_path() {
    local p="$1" tail=""
    [[ $p == /* || $p =~ ^[A-Za-z]: ]] || p="${PWD}/${p}"
    while [[ ! -d "$p" ]]; do
        tail="/$(basename "$p")${tail}"
        p="$(dirname "$p")"
    done
    p="$(cd -P "$p" && pwd -P)${tail}"
    case "${OSTYPE:-}" in
        msys*|cygwin*) p="$(printf '%s' "$p" | tr '[:upper:]' '[:lower:]')" ;;
    esac
    printf '%s\n' "${p%/}"
}

# True if path $1 is dir $2 or lies inside it.
path_within() {
    local p d
    p="$(norm_path "$1")"
    d="$(norm_path "$2")"
    [[ "$p" == "$d" || "$p" == "$d"/* ]]
}

# Nudge alerts: the same DB path nudge_db.py resolves for a script install
# into CLAUDE_DIR, with a leading ~ expanded the way nudge_db.py does it. The
# runtime merges every *.db in the nudge-import dir next to the DB on its next
# run, so I hand a legacy DB over by dropping it there; I never merge myself.
# NUDGE_MARKER_DIR is always under CLAUDE_DIR, even with an override: the
# runtime uses it to recognize a script-install root.
# I trim the override the way the runtime's .strip() does, so a whitespace-only
# value counts as unset in both places.
NUDGE_DB_OVERRIDE="${CLAYWORKS_NUDGE_DB:-}"
NUDGE_DB_OVERRIDE="${NUDGE_DB_OVERRIDE#"${NUDGE_DB_OVERRIDE%%[![:space:]]*}"}"
NUDGE_DB_OVERRIDE="${NUDGE_DB_OVERRIDE%"${NUDGE_DB_OVERRIDE##*[![:space:]]}"}"
NUDGE_DB="${NUDGE_DB_OVERRIDE:-${CLAUDE_DIR}/clayworks-lite/nudge/alerts.db}"
if [[ $NUDGE_DB == \~ || $NUDGE_DB == \~/* ]]; then
    NUDGE_DB="${HOME}${NUDGE_DB:1}"
elif [[ $NUDGE_DB == \~* ]]; then
    # ~alice/... means another user's home. Python expands it one way, and I
    # can't match that reliably on every platform, so I refuse it rather than
    # hand your alerts to a folder the runtime never scans.
    echo "ERROR: CLAYWORKS_NUDGE_DB (${NUDGE_DB}) uses a ~user path. Set it to a full path instead." >&2
    exit 2
fi
# Git Bash passes a Windows-style override through verbatim (C:\Users\me\alerts.db),
# and POSIX dirname can't split on backslashes, so it would put nudge-import/ in
# the current directory while the runtime (Windows Python) looks next to the
# real file. I convert it to the POSIX form first when cygpath is available.
if [[ $NUDGE_DB =~ ^[A-Za-z]:[\\/] || $NUDGE_DB == *\\* ]] && command -v cygpath >/dev/null 2>&1; then
    NUDGE_DB="$(cygpath -u "$NUDGE_DB")"
fi
NUDGE_MARKER_DIR="${CLAUDE_DIR}/clayworks-lite/nudge"
NUDGE_SKILL_DIR="${CLAUDE_DIR}/skills/clayworks-lite-nudge"
NUDGE_IMPORT_DIR="$(dirname "$NUDGE_DB")/nudge-import"
# Alert stores that live inside the Nudge skill dir, as relpaths from it:
# where 1.0.x kept the DB, plus the CLAYWORKS_NUDGE_DB file when it points in
# there. Install replaces that dir and uninstall removes it, so I hand every
# one of them to nudge-import/ first.
NUDGE_STORE_RELS=("scripts/alerts.db")
# If CLAYWORKS_NUDGE_DB points inside the Nudge skill dir, a nudge-import dir
# next to it would go down with that dir. I fall back to the default Nudge
# dir and warn.
NUDGE_DB_IN_SKILL=0
if path_within "$NUDGE_DB" "$NUDGE_SKILL_DIR" || path_within "$NUDGE_IMPORT_DIR" "$NUDGE_SKILL_DIR"; then
    NUDGE_DB_IN_SKILL=1
    NUDGE_IMPORT_DIR="${NUDGE_MARKER_DIR}/nudge-import"
    nudge_db_norm="$(norm_path "$NUDGE_DB")"
    nudge_skill_norm="$(norm_path "$NUDGE_SKILL_DIR")"
    if [[ "$nudge_db_norm" == "$nudge_skill_norm"/* && "${nudge_db_norm#"$nudge_skill_norm"/}" != "scripts/alerts.db" ]]; then
        NUDGE_STORE_RELS+=("${nudge_db_norm#"$nudge_skill_norm"/}")
    fi
fi

# True if relpath $1 inside the Nudge skill dir is one of NUDGE_STORE_RELS
# or its -wal / -shm / -journal sidecar. norm_path lowercases on Git Bash, so I match
# case-insensitively there.
is_nudge_store_rel() {
    local f="$1" s
    case "${OSTYPE:-}" in
        msys*|cygwin*) f="$(printf '%s' "$f" | tr '[:upper:]' '[:lower:]')" ;;
    esac
    for s in "${NUDGE_STORE_RELS[@]}"; do
        if [[ "$f" == "$s" || "$f" == "${s}-wal" || "$f" == "${s}-shm" || "$f" == "${s}-journal" ]]; then
            return 0
        fi
    done
    return 1
}

warn_nudge_db_in_skill() {
    [[ $NUDGE_DB_IN_SKILL -eq 1 ]] || return 0
    echo "  ${C_YELLOW}WARNING: CLAYWORKS_NUDGE_DB (${NUDGE_DB}) points inside ${NUDGE_SKILL_DIR},${C_RESET}"
    echo "  ${C_YELLOW}which install replaces and uninstall removes. I hand its alerts to${C_RESET}"
    echo "  ${C_YELLOW}${NUDGE_IMPORT_DIR} instead. Point CLAYWORKS_NUDGE_DB somewhere else.${C_RESET}"
}

# .installer/shipped-hashes.txt lists "<installed-relpath><TAB><sha256>" for
# every version of every file LITE ever shipped (tools/gen-shipped-hashes.py
# writes it from git history). Uninstall uses it to recognize an older
# version's files as mine to remove. I strip CR so a CRLF copy still matches,
# and pad with newlines so every entry sits between two of them.
SHIPPED_MANIFEST="${REPO_ROOT}/.installer/shipped-hashes.txt"
SHIPPED_LINES=""
if [[ -f "$SHIPPED_MANIFEST" ]]; then
    SHIPPED_LINES=$'\n'"$(tr -d '\r' < "$SHIPPED_MANIFEST")"$'\n'
fi

# --- Hashing (prefer sha256sum, fall back to shasum on macOS) ----------------

# sha_file reads the file on stdin rather than by name: GNU sha256sum prefixes
# its output with a backslash when the path contains one (e.g. a Windows-style
# --claude-dir under Git Bash), which would break the hash comparison.
if command -v sha256sum >/dev/null 2>&1; then
    sha_file()  { sha256sum < "$1" | awk '{print $1}'; }
    sha_stdin() { sha256sum        | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
    sha_file()  { shasum -a 256 < "$1" | awk '{print $1}'; }
    sha_stdin() { shasum -a 256        | awk '{print $1}'; }
else
    echo "ERROR: need sha256sum or shasum on PATH" >&2
    exit 3
fi

# Hash a file (sha256) or a directory (sha256 over sorted "relpath:filehash" lines).
# Excludes symlinks from the directory walk so the hash is deterministic against
# an attacker that might swap a symlink's target between hash and copy (TOCTOU).
# A non-empty second argument leaves out the Nudge alert stores (see
# is_nudge_store_rel).
path_hash() {
    local path="$1" ignore="${2:-}"
    if [[ ! -e "$path" ]]; then echo ""; return; fi
    if [[ -f "$path" ]]; then sha_file "$path"; return; fi
    if [[ -d "$path" ]]; then
        (
            cd "$path"
            find . -type f -not -type l -print0 | LC_ALL=C sort -z | while IFS= read -r -d '' f; do
                if [[ -n "$ignore" ]] && is_nudge_store_rel "${f#./}"; then continue; fi
                printf '%s:%s\n' "${f#./}" "$(sha_file "$f")"
            done
        ) | sha_stdin
        return
    fi
}

# Refuse to install a source tree containing symlinks.
# Supply-chain hardening: a tampered clone could include symlinks pointing at
# arbitrary files (e.g., ~/.ssh/id_ed25519). `cp -R` would dereference them and
# write their *contents* into ~/.claude/, creating a predictable exfil channel.
# Rejecting symlinks at the source means an honest LITE source tree (which has
# none) installs fine while a tampered tree aborts loudly.
reject_symlinks_in_source() {
    local src="$1"
    [[ ! -d "$src" ]] && return 0
    local found
    found="$(find "$src" -type l -print 2>/dev/null)"
    if [[ -n "$found" ]]; then
        echo "ERROR: source tree contains symlinks (potential supply-chain risk):" >&2
        while IFS= read -r line; do
            printf '  %s\n' "$line" >&2
        done <<< "$found"
        echo "" >&2
        echo "The LITE source tree should contain no symlinks. If you cloned from" >&2
        echo "github.com/clayboicardi/clayworks-lite and see this error, your" >&2
        echo "working copy may have been tampered with. Re-clone before installing." >&2
        exit 4
    fi
}

# --- State -------------------------------------------------------------------

INSTALLED=()
UPDATED=()
SKIPPED=()
BACKUP_PATHS=()

# --- Python discovery --------------------------------------------------------
# The Nudge scripts and JSON checks need Python 3.10+. The executable name
# varies: python3 on macOS/Linux, often only python or the py launcher on
# Windows (where "python3" may be a Store alias that just prints a hint).
# PYTHON_CMD ends up as an array ("python3" / "python" / "py -3"), or empty.

PYTHON_CMD=()
find_python() {
    local probe='import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    local c
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c "$probe" >/dev/null 2>&1; then
            PYTHON_CMD=("$c"); return 0
        fi
    done
    if command -v py >/dev/null 2>&1 && py -3 -c "$probe" >/dev/null 2>&1; then
        PYTHON_CMD=(py -3); return 0
    fi
    return 1
}

# --- Output helpers ----------------------------------------------------------

if [[ -t 1 ]]; then
    C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_DIM=$'\033[2m';   C_RESET=$'\033[0m'
else
    C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_DIM=""; C_RESET=""
fi

section() { echo; echo "${C_CYAN}==> $1${C_RESET}"; }
info()    { echo "    $1"; }
added()   { echo "  ${C_GREEN}+ $1${C_RESET}"; }
upd()     { echo "  ${C_YELLOW}~ $1${C_RESET}"; }
skip()    { echo "  ${C_DIM}- $1${C_RESET}"; }

# --- Operations --------------------------------------------------------------

backup_path() {
    local dest="$1" rel="$2"
    local target="${BACKUP_DIR}/${rel}"
    mkdir -p "$(dirname "$target")"
    cp -R "$dest" "$target"
    BACKUP_PATHS+=("$target")
}

install_item() {
    local src="$1" dest="$2" label="$3" backup_rel="$4"

    if [[ ! -e "$src" ]]; then
        skip "${label}: source missing in repo (skipped)"
        return
    fi

    local dest_parent
    dest_parent="$(dirname "$dest")"
    if [[ ! -d "$dest_parent" && $DRY_RUN -eq 0 ]]; then
        mkdir -p "$dest_parent"
    fi

    if [[ ! -e "$dest" ]]; then
        if [[ $DRY_RUN -eq 0 ]]; then
            # -P preserves symlinks as symlinks instead of following them.
            # Belt-and-suspenders with reject_symlinks_in_source() above.
            if [[ -d "$src" ]]; then cp -RP "$src" "$dest"; else cp -P "$src" "$dest"; fi
        fi
        added "${label} -> ${dest}"
        INSTALLED+=("$label")
        return
    fi

    local src_hash dest_hash
    src_hash="$(path_hash "$src")"
    dest_hash="$(path_hash "$dest")"

    if [[ "$src_hash" == "$dest_hash" ]]; then
        skip "${label}: already installed and unchanged"
        SKIPPED+=("$label")
        return
    fi

    if [[ $DRY_RUN -eq 0 ]]; then
        backup_path "$dest" "$backup_rel"
        rm -rf "$dest"
        if [[ -d "$src" ]]; then cp -RP "$src" "$dest"; else cp -P "$src" "$dest"; fi
    fi
    upd "${label}: differed from source -> backed up + reinstalled"
    UPDATED+=("$label")
}

# --- Nudge alerts DB: hand a pre-1.1.0 DB to the runtime --------------------
# Before 1.1.0 the Nudge DB lived inside the skill dir, which install replaces
# wholesale and uninstall removes. I move that legacy DB into nudge-import/
# before either one touches the skill dir, and the runtime merges it into the
# stable DB on its next run. I never merge, and I never skip the move because
# the stable DB already exists: a legacy DB left behind would end up in a
# backup folder or deleted.

# Exit before touching anything if a path component below CLAUDE_DIR, down to
# $1, is a symlink (Git Bash reports a Windows junction as one too). A
# symlinked clayworks-lite/ or nudge/ would send your reminders outside the
# install root, and a symlinked skills/ or skill dir would have me move or
# delete files in whatever folder it points at. CLAUDE_DIR itself may be a
# symlink (dotfile setups do that), so I only check components under it.
# Paths outside CLAUDE_DIR, like a CLAYWORKS_NUDGE_DB you chose, are yours to
# lay out, so I leave them alone.
refuse_symlink_under_root() {
    local target="$1" p="$CLAUDE_DIR" part parts=()
    [[ "$target" == "$CLAUDE_DIR"/* ]] || return 0
    IFS=/ read -r -a parts <<< "${target#"$CLAUDE_DIR"/}"
    for part in "${parts[@]}"; do
        [[ -n "$part" ]] || continue
        p="${p}/${part}"
        if [[ -L "$p" ]]; then
            echo "ERROR: ${p} is a symlink or junction. I won't read, move, or write LITE" >&2
            echo "files through it, because it can point outside ${CLAUDE_DIR}. Replace" >&2
            echo "it with a real directory or file, then re-run." >&2
            exit 5
        fi
    done
}

# Check every Nudge path under CLAUDE_DIR up front, before I read, move, or
# write anything: the data dirs, the alerts DB file itself and its SQLite
# sidecars (a symlinked alerts.db would have Nudge write reminders into
# whatever it points at), plus skills/, the Nudge skill dir, and its
# scripts/, where legacy stores live.
refuse_nudge_symlinks() {
    local side
    refuse_symlink_under_root "${NUDGE_MARKER_DIR}/nudge-import"
    refuse_symlink_under_root "$NUDGE_IMPORT_DIR"
    for side in "" -journal -wal -shm; do
        refuse_symlink_under_root "${NUDGE_DB}${side}"
    done
    refuse_symlink_under_root "${NUDGE_SKILL_DIR}/scripts"
    # Every legacy store I might stash, and its sidecars: a linked one would
    # have me move the link and Nudge import an unrelated external database.
    local s
    for s in "${NUDGE_STORE_RELS[@]}"; do
        for side in "" -journal -wal -shm; do
            refuse_symlink_under_root "${NUDGE_SKILL_DIR}/${s}${side}"
        done
    done
}

# mkdir -p that tightens to 700 only the dirs it actually creates. If
# CLAYWORKS_NUDGE_DB points into an existing shared dir, its owner's
# permissions stay as they are.
make_private_dir() {
    local dir="$1" d="$1" created=()
    refuse_symlink_under_root "$dir"
    while [[ ! -d "$d" ]]; do
        created+=("$d")
        d="$(dirname "$d")"
    done
    [[ ${#created[@]} -gt 0 ]] || return 0
    mkdir -p "$dir"
    for d in "${created[@]}"; do
        chmod 700 "$d" 2>/dev/null || true
    done
}

# Move one alert store to nudge-import/legacy-<timestamp>-<pid>.db, where
# Nudge merges it. Its -wal / -shm / -journal sidecars move with it under
# the same new name, so SQLite still finds a hot journal after a crash.
stash_nudge_store() {
    local src="$1" label="$2"
    local base="${NUDGE_IMPORT_DIR}/legacy-${TIMESTAMP}" target n=1 ext
    target="${base}.db"
    while [[ -e "$target" ]]; do
        target="${base}-${n}.db"
        n=$((n+1))
    done
    if [[ $DRY_RUN -eq 1 ]]; then
        upd "would move ${label} -> ${target} (Nudge merges it on its next run)"
        return 0
    fi
    make_private_dir "$NUDGE_IMPORT_DIR"
    mv "$src" "$target"
    for ext in -wal -shm -journal; do
        if [[ -f "${src}${ext}" ]]; then
            mv "${src}${ext}" "${target}${ext}"
        fi
    done
    upd "moved ${label} -> ${target} (Nudge merges it on its next run)"
}

# Hand every alert store inside skill dir $1 to nudge-import/. Returns 1 if
# there was none.
stash_nudge_stores() {
    local s found=1
    for s in "${NUDGE_STORE_RELS[@]}"; do
        if [[ -f "$1/$s" ]]; then
            stash_nudge_store "$1/$s" "$s"
            found=0
        fi
    done
    return $found
}

# --- Uninstall operation -----------------------------------------------------

KEPT=0

# True if the manifest lists this exact (installed-relpath, sha256) pair.
is_shipped_file() {
    [[ "$SHIPPED_LINES" == *$'\n'"$1"$'\t'"$2"$'\n'* ]]
}

# True if dest holds nothing but files some LITE version shipped at the same
# installed path, apart from the optional ignore relpath. I also skip *.pyc
# files directly inside a __pycache__/ dir, which 1.0.x left behind by
# running Python from inside the skill dir. A .pyc anywhere else is yours, so
# it counts. A symlink, an extra file, or an edited file means you touched
# it, so the answer is no.
matches_shipped_version() {
    local dest="$1" rel="$2" ignore="${3:-}"
    [[ -n "$SHIPPED_LINES" && ! -L "$dest" ]] || return 1
    if [[ -f "$dest" ]]; then
        is_shipped_file "$rel" "$(sha_file "$dest")"
        return
    fi
    [[ -d "$dest" ]] || return 1
    [[ -z "$(find "$dest" -type l -print -quit)" ]] || return 1
    local f parent
    while IFS= read -r -d '' f; do
        f="${f#./}"
        parent="${f%/*}"
        parent="${parent##*/}"
        if [[ "$f" == */* && "$parent" == "__pycache__" && "$f" == *.pyc ]]; then continue; fi
        if [[ -n "$ignore" ]] && is_nudge_store_rel "$f"; then continue; fi
        is_shipped_file "${rel}/${f}" "$(sha_file "${dest}/${f}")" || return 1
    done < <(cd "$dest" && find . -type f -print0)
    return 0
}

# Remove dest if it matches the current source, or failing that, if every
# file in it matches some shipped version. Otherwise keep it and count it.
# A non-empty fifth argument marks the Nudge skill dir: I leave its alert
# stores (NUDGE_STORE_RELS) out of that decision. When dest goes, I hand
# them to the nudge-import dir first; when dest stays, they stay with it,
# because the retained 1.0.x scripts still read them there.
uninstall_item() {
    local dest="$1" src="$2" label="$3" rel="$4" ignore="${5:-}"

    if [[ ! -e "$dest" ]]; then
        skip "${label}: not present (already uninstalled)"
        return
    fi

    local how
    if [[ -e "$src" && "$(path_hash "$src" "$ignore")" == "$(path_hash "$dest" "$ignore")" ]]; then
        how="removed"
    elif matches_shipped_version "$dest" "$rel" "$ignore"; then
        how="removed (matches a shipped LITE version)"
    else
        upd "${label}: customized (differs from every shipped version) — SKIPPING; remove manually if you want"
        KEPT=$((KEPT+1))
        return
    fi

    if [[ -n "$ignore" ]]; then
        stash_nudge_stores "$dest" || true
    fi
    if [[ $DRY_RUN -eq 0 ]]; then
        rm -rf "$dest"
    fi
    added "${label}: ${how}"
}

run_uninstall() {
    echo
    echo "${C_CYAN}Clayworks LITE uninstaller${C_RESET}"
    echo "============================================================"
    info "Source repo  : ${REPO_ROOT}"
    info "Install root : ${CLAUDE_DIR}"
    if [[ $DRY_RUN -eq 1 ]]; then
        info "Mode         : DRY RUN (no changes written)"
    else
        info "Mode         : LIVE"
    fi
    refuse_nudge_symlinks
    warn_nudge_db_in_skill

    section "Removing LITE skills"
    local skills_src="${REPO_ROOT}/plugin/skills"
    local skills_dest="${CLAUDE_DIR}/skills"
    # Every skill the current tree ships, plus any an older version shipped.
    # A 1.0.x Nudge skill dir still holds its runtime DB, which I leave out
    # of the keep-or-remove decision.
    local name ignore
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        ignore=""
        [[ "$name" == "clayworks-lite-nudge" ]] && ignore="nudge-stores"
        uninstall_item "${skills_dest}/${name}" "${skills_src}/${name}" "skill: ${name}" "skills/${name}" "$ignore"
    done < <(
        {
            if [[ -d "$skills_src" ]]; then
                find "$skills_src" -mindepth 1 -maxdepth 1 -type d -name "clayworks-lite-*" | sed 's|.*/||'
            fi
            printf '%s' "$SHIPPED_LINES" | awk -F'[/\t]' '$1 == "skills" && $2 ~ /^clayworks-lite-/ { print $2 }'
        } | LC_ALL=C sort -u
    )

    section "Removing hook examples"
    uninstall_item "${CLAUDE_DIR}/hooks/examples" "${REPO_ROOT}/plugin/hooks/examples" "hooks/examples" "hooks/examples"

    section "Removing CLAUDE.md starter template"
    uninstall_item "${CLAUDE_DIR}/CLAUDE.md.clayworks-template" "${REPO_ROOT}/plugin/templates/CLAUDE.md.clayworks-template" "CLAUDE.md.clayworks-template" "CLAUDE.md.clayworks-template"

    section "Removing settings.example.json"
    uninstall_item "${CLAUDE_DIR}/settings.example.json" "${REPO_ROOT}/plugin/templates/settings.example.json" "settings.example.json" "settings.example.json"

    section "Did NOT touch"
    info "  ${CLAUDE_DIR}/CLAUDE.md (your live config)"
    info "  ${CLAUDE_DIR}/settings.json (your live config)"
    info "  ${CLAUDE_DIR}/hooks/  (excluding examples/ subdir handled above)"
    info "  ${NUDGE_DB} and ${NUDGE_IMPORT_DIR}/ (your Nudge alerts — remove manually if desired)"
    info "  ${BACKUP_ROOT}/ (your backups — remove manually if desired)"

    section "Next steps"
    cat <<EOF
If you wired Nudge or other LITE hooks into ${CLAUDE_DIR}/settings.json,
remove those entries manually. The uninstaller can't safely edit
your settings.json — JSON parsing of an arbitrary user file would
be too fragile. A leftover Nudge hook entry points at a launcher
that no longer exists, so it shows a hook error on every prompt.

To purge the backup folder and your Nudge alerts:
EOF
    # I list only paths LITE owns. An override's DB may sit in a shared dir,
    # so I name the DB file and the nudge-import dir, never their parent.
    # %q quotes each path so a name like O'Brien pastes back safely.
    local lite_dir="${CLAUDE_DIR}/clayworks-lite"
    printf '  rm -rf %q\n' "$BACKUP_ROOT" "$lite_dir"
    if ! path_within "$NUDGE_DB" "$lite_dir"; then
        printf '  rm -f %q\n' "$NUDGE_DB"
    fi
    if ! path_within "$NUDGE_IMPORT_DIR" "$lite_dir"; then
        printf '  rm -rf %q\n' "$NUDGE_IMPORT_DIR"
    fi
    echo
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "${C_CYAN}DRY RUN - nothing removed.${C_RESET}"
    fi
    if [[ $KEPT -gt 0 ]]; then
        echo "${C_YELLOW}Uninstall finished; ${KEPT} item(s) kept because they differ from any shipped version.${C_RESET}"
    else
        echo "${C_GREEN}Uninstall complete.${C_RESET}"
    fi
}

# --- Verify operation --------------------------------------------------------

verify_check() {
    local label="$1" status="$2" detail="$3"
    case "$status" in
        pass) added "${label}: ${detail}";;
        warn) upd "${label}: ${detail}";;
        skip) skip "${label}: ${detail}";;
        fail) echo "  ${C_YELLOW}? ${label}: ${detail}${C_RESET}"; VERIFY_FAILS=$((VERIFY_FAILS+1));;
    esac
}

run_verify() {
    echo
    echo "${C_CYAN}Clayworks LITE — verify install${C_RESET}"
    echo "============================================================"
    info "Install root : ${CLAUDE_DIR}"
    VERIFY_FAILS=0

    section "Runtime"
    if find_python; then
        verify_check "python (${PYTHON_CMD[*]})" pass "$("${PYTHON_CMD[@]}" --version 2>&1)"
        if [[ "${PYTHON_CMD[0]}" != "python3" ]]; then
            verify_check "python3 name" warn "not on PATH; the Nudge hook launcher falls back to '${PYTHON_CMD[*]}', but the hook examples call python3 by name"
        fi
        if "${PYTHON_CMD[@]}" -c "import sqlite3" 2>/dev/null; then
            verify_check "python sqlite3 import" pass "ok"
        else
            verify_check "python sqlite3 import" fail "cannot import — Nudge skill will not work"
        fi
    else
        verify_check "python" warn "no Python 3.10+ found (tried python3, python, py -3) — Nudge skill + hook examples will not work until you install one"
    fi
    if command -v claude >/dev/null 2>&1; then
        verify_check "claude" pass "$(claude --version 2>&1 | head -1)"
    else
        verify_check "claude" warn "not on PATH (CC may be installed but invoked differently)"
    fi

    section "Skills"
    local s
    for s in clayworks-lite-nudge clayworks-lite-memory-routing clayworks-lite-heartbeat-concept; do
        local f="${CLAUDE_DIR}/skills/${s}/SKILL.md"
        if [[ -f "$f" ]]; then
            if head -1 "$f" | grep -q '^---$'; then
                verify_check "${s}" pass "SKILL.md present + frontmatter ok"
            else
                verify_check "${s}" fail "SKILL.md present but frontmatter missing/malformed"
            fi
        else
            verify_check "${s}" fail "SKILL.md missing at ${f}"
        fi
    done

    section "Nudge hook launcher"
    local nd="${CLAUDE_DIR}/skills/clayworks-lite-nudge/scripts"
    local nf
    for nf in run-python.sh nudge_db.py check_alerts.py; do
        if [[ -f "${nd}/${nf}" ]]; then
            verify_check "nudge/scripts/${nf}" pass "present"
        else
            verify_check "nudge/scripts/${nf}" fail "missing at ${nd}/${nf}"
        fi
    done

    section "Hook examples"
    local h
    for h in userpromptsubmit pretooluse posttooluse sessionstart sessionend stop subagentstart subagentstop; do
        local f="${CLAUDE_DIR}/hooks/examples/${h}.sh"
        if [[ -f "$f" ]]; then
            if head -1 "$f" | grep -q '^#!/usr/bin/env bash'; then
                verify_check "hooks/examples/${h}.sh" pass "present + shebang ok"
            else
                verify_check "hooks/examples/${h}.sh" fail "present but shebang missing/corrupt (LF vs CRLF?)"
            fi
        else
            verify_check "hooks/examples/${h}.sh" fail "missing"
        fi
    done

    section "Templates"
    local tmpl="${CLAUDE_DIR}/CLAUDE.md.clayworks-template"
    if [[ -f "$tmpl" ]]; then
        verify_check "CLAUDE.md.clayworks-template" pass "present"
    else
        verify_check "CLAUDE.md.clayworks-template" fail "missing at ${tmpl}"
    fi
    local setj="${CLAUDE_DIR}/settings.example.json"
    if [[ -f "$setj" ]]; then
        # Pipe via stdin to dodge Git-Bash/Windows-Python path-space mismatch
        # (bash's POSIX-style /tmp/... isn't visible to Windows Python).
        if [[ ${#PYTHON_CMD[@]} -eq 0 ]]; then
            verify_check "settings.example.json" skip "present; JSON check skipped (no Python found)"
        elif "${PYTHON_CMD[@]}" -c "import json, sys; json.load(sys.stdin)" < "$setj" 2>/dev/null; then
            verify_check "settings.example.json" pass "present + valid JSON"
        else
            verify_check "settings.example.json" fail "present but JSON parse failed"
        fi
    else
        verify_check "settings.example.json" fail "missing at ${setj}"
    fi

    section "Verify summary"
    if [[ $VERIFY_FAILS -eq 0 ]]; then
        echo "  ${C_GREEN}PASS: all checks passed${C_RESET}"
        exit 0
    else
        echo "  ${C_YELLOW}WARN: ${VERIFY_FAILS} check(s) need attention${C_RESET}"
        exit 1
    fi
}

# --- Dispatch ---------------------------------------------------------------
# Output helpers (section/info/added/upd/skip) are defined above in the
# "Output helpers" section and remain in scope here.

if [[ $VERIFY -eq 1 ]]; then
    run_verify
fi

if [[ $UNINSTALL -eq 1 ]]; then
    run_uninstall
    exit 0
fi

# --- Pre-flight --------------------------------------------------------------

echo
echo "${C_CYAN}Clayworks LITE installer${C_RESET}"
echo "============================================================"
info "Source repo  : ${REPO_ROOT}"
info "Install root : ${CLAUDE_DIR}"
if [[ $DRY_RUN -eq 1 ]]; then
    info "Mode         : DRY RUN (no changes written)"
else
    info "Mode         : LIVE"
fi

if [[ ! -d "$CLAUDE_DIR" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
        info "Would create install root: ${CLAUDE_DIR}"
    else
        mkdir -p "$CLAUDE_DIR"
        info "Created install root: ${CLAUDE_DIR}"
    fi
fi

# Supply-chain check: refuse to proceed if the source tree contains symlinks.
reject_symlinks_in_source "$REPO_ROOT"
# Refuse a symlinked Nudge dir under the install root before any write.
refuse_nudge_symlinks

section "Nudge alerts database"
warn_nudge_db_in_skill
# I always create the default Nudge dir: the runtime treats it as the sign
# that this root holds a script install.
if [[ -d "$NUDGE_MARKER_DIR" ]]; then
    skip "${NUDGE_MARKER_DIR}: already present"
elif [[ $DRY_RUN -eq 1 ]]; then
    added "would create ${NUDGE_MARKER_DIR}"
else
    make_private_dir "$NUDGE_MARKER_DIR"
    added "created ${NUDGE_MARKER_DIR}"
fi
# Hand every alert store in the skill dir to the runtime before I replace it.
if ! stash_nudge_stores "$NUDGE_SKILL_DIR"; then
    skip "nothing to migrate (alerts live in ${NUDGE_DB})"
fi

# --- Install items -----------------------------------------------------------

section "Installing skills"
skills_src="${REPO_ROOT}/plugin/skills"
skills_dest="${CLAUDE_DIR}/skills"
if [[ -d "$skills_src" ]]; then
    found=0
    while IFS= read -r d; do
        [[ -z "$d" ]] && continue
        name="$(basename "$d")"
        install_item "$d" "${skills_dest}/${name}" "skill: ${name}" "skills/${name}"
        found=1
    done < <(find "$skills_src" -mindepth 1 -maxdepth 1 -type d -name "clayworks-lite-*" 2>/dev/null | LC_ALL=C sort)
    if [[ $found -eq 0 ]]; then
        skip "No clayworks-lite-* skills found in repo"
    fi
else
    skip "No skills/ directory in repo (nothing to install)"
fi

section "Installing hook examples"
install_item \
    "${REPO_ROOT}/plugin/hooks/examples" \
    "${CLAUDE_DIR}/hooks/examples" \
    "hooks/examples" \
    "hooks/examples"

section "Installing CLAUDE.md starter template"
install_item \
    "${REPO_ROOT}/plugin/templates/CLAUDE.md.clayworks-template" \
    "${CLAUDE_DIR}/CLAUDE.md.clayworks-template" \
    "CLAUDE.md.clayworks-template" \
    "CLAUDE.md.clayworks-template"

section "Installing settings.example.json"
install_item \
    "${REPO_ROOT}/plugin/templates/settings.example.json" \
    "${CLAUDE_DIR}/settings.example.json" \
    "settings.example.json" \
    "settings.example.json"

# --- Summary -----------------------------------------------------------------

section "Summary"
info "Installed (new) : ${#INSTALLED[@]}"
if [[ ${#INSTALLED[@]} -gt 0 ]]; then
    for i in "${INSTALLED[@]}"; do echo "    ${C_GREEN}+ $i${C_RESET}"; done
fi
info "Updated  (diff) : ${#UPDATED[@]}"
if [[ ${#UPDATED[@]} -gt 0 ]]; then
    for u in "${UPDATED[@]}";   do echo "    ${C_YELLOW}~ $u${C_RESET}"; done
fi
info "Skipped (same)  : ${#SKIPPED[@]}"
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
    for s in "${SKIPPED[@]}";   do echo "    ${C_DIM}- $s${C_RESET}"; done
fi

if [[ ${#BACKUP_PATHS[@]} -gt 0 ]]; then
    echo
    echo "${C_CYAN}Backups written to:${C_RESET}"
    echo "  ${BACKUP_DIR}"
    echo "If you had local edits, they're preserved there."
fi

if [[ $DRY_RUN -eq 1 ]]; then
    echo
    echo "${C_CYAN}DRY RUN COMPLETE - no files written.${C_RESET}"
    echo "Re-run without --dry-run to actually install."
    exit 0
fi

# --- Next steps --------------------------------------------------------------

section "Next steps"
# I print the chosen root, shell-quoted, so each command pastes back as-is
# even for a --claude-dir with spaces or quotes.
R="$(printf '%q' "$CLAUDE_DIR")"
cat <<EOF
1. Claude Code picks up new skills in a running session. If
     ${R}/skills/ didn't exist before this install, start a new
     session so Claude Code can watch the new directory.

2. To use the CLAUDE.md starter template:
     cp ${R}/CLAUDE.md.clayworks-template ${R}/CLAUDE.md
     (back up any existing ${R}/CLAUDE.md first)
     then edit the <YOUR ...> placeholders.

3. To use the nudge skill (if installed):
     the skill auto-triggers when you mention a time
     ("stop me at 5pm", "remind me about standup at 9:55").
     For nudges to actually fire, add the UserPromptSubmit hook from
     ${R}/settings.example.json to ${R}/settings.json
     (details in ${R}/skills/clayworks-lite-nudge/SKILL.md).
     Claude Code applies settings.json edits without a restart.
     Skip this if you also installed LITE as a plugin: the plugin
     registers the same hook, and you'd see every alert twice.

4. To use a hook example:
     cp ${R}/hooks/examples/<event>.sh ${R}/hooks/<name>.sh
     customize, then register it in ${R}/settings.json (see the README
     inside the examples/ dir).

Verify the install:
     ls ${R}/skills/clayworks-lite-*/
EOF

echo
echo "${C_GREEN}Done.${C_RESET}"
