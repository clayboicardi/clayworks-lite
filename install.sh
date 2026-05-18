#!/usr/bin/env bash
# Clayworks LITE installer - macOS / Linux / Git Bash on Windows
# https://github.com/clayboicardi/clayworks-lite
#
# Installs the Clayworks LITE components into ~/.claude/ without clobbering
# your existing setup. Any file the installer is about to overwrite is first
# copied to ~/.claude/.clayworks-lite-backup/<timestamp>/.
#
# Usage: ./install.sh [--dry-run] [--claude-dir PATH]

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
\$CLAUDE_DIR/hooks/ are never touched.
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

# --- Hashing (prefer sha256sum, fall back to shasum on macOS) ----------------

if command -v sha256sum >/dev/null 2>&1; then
    sha_file()  { sha256sum  "$1" | awk '{print $1}'; }
    sha_stdin() { sha256sum     | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
    sha_file()  { shasum -a 256 "$1" | awk '{print $1}'; }
    sha_stdin() { shasum -a 256     | awk '{print $1}'; }
else
    echo "ERROR: need sha256sum or shasum on PATH" >&2
    exit 3
fi

# Hash a file (sha256) or a directory (sha256 over sorted "relpath:filehash" lines).
# Excludes symlinks from the directory walk so the hash is deterministic against
# an attacker that might swap a symlink's target between hash and copy (TOCTOU).
path_hash() {
    local path="$1"
    if [[ ! -e "$path" ]]; then echo ""; return; fi
    if [[ -f "$path" ]]; then sha_file "$path"; return; fi
    if [[ -d "$path" ]]; then
        (
            cd "$path"
            find . -type f -not -type l -print0 | LC_ALL=C sort -z | while IFS= read -r -d '' f; do
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

# --- Uninstall operation -----------------------------------------------------

uninstall_item() {
    local dest="$1" src="$2" label="$3"

    if [[ ! -e "$dest" ]]; then
        skip "${label}: not present (already uninstalled)"
        return
    fi

    if [[ -e "$src" ]]; then
        local src_hash dest_hash
        src_hash="$(path_hash "$src")"
        dest_hash="$(path_hash "$dest")"
        if [[ "$src_hash" != "$dest_hash" ]]; then
            upd "${label}: customized (hash differs from source) — SKIPPING; remove manually if you want"
            return
        fi
    fi

    if [[ $DRY_RUN -eq 0 ]]; then
        rm -rf "$dest"
    fi
    added "${label}: removed"
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

    section "Removing LITE skills"
    local skills_src="${REPO_ROOT}/skills"
    local skills_dest="${CLAUDE_DIR}/skills"
    if [[ -d "$skills_src" ]]; then
        while IFS= read -r d; do
            [[ -z "$d" ]] && continue
            local name; name="$(basename "$d")"
            uninstall_item "${skills_dest}/${name}" "$d" "skill: ${name}"
        done < <(find "$skills_src" -mindepth 1 -maxdepth 1 -type d -name "clayworks-lite-*" 2>/dev/null | LC_ALL=C sort)
    fi

    section "Removing hook examples"
    uninstall_item "${CLAUDE_DIR}/hooks/examples" "${REPO_ROOT}/hooks/examples" "hooks/examples"

    section "Removing CLAUDE.md starter template"
    uninstall_item "${CLAUDE_DIR}/CLAUDE.md.clayworks-template" "${REPO_ROOT}/templates/CLAUDE.md.clayworks-template" "CLAUDE.md.clayworks-template"

    section "Removing settings.example.json"
    uninstall_item "${CLAUDE_DIR}/settings.example.json" "${REPO_ROOT}/templates/settings.example.json" "settings.example.json"

    section "Did NOT touch"
    info "  ${CLAUDE_DIR}/CLAUDE.md (your live config)"
    info "  ${CLAUDE_DIR}/settings.json (your live config)"
    info "  ${CLAUDE_DIR}/hooks/  (excluding examples/ subdir handled above)"
    info "  ${CLAUDE_DIR}/.clayworks-lite-backup/ (your backups — remove manually if desired)"

    section "Next steps"
    cat <<'EOF'
If you wired Nudge or other LITE hooks into ~/.claude/settings.json,
remove those entries manually. The uninstaller can't safely edit
your settings.json — JSON parsing of an arbitrary user file would
be too fragile.

To purge the backup folder:
  rm -rf ~/.claude/.clayworks-lite-backup
EOF
    echo
    echo "${C_GREEN}Uninstall complete.${C_RESET}"
}

# --- Verify operation --------------------------------------------------------

verify_check() {
    local label="$1" status="$2" detail="$3"
    case "$status" in
        pass) added "${label}: ${detail}";;
        warn) upd "${label}: ${detail}";;
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
    if command -v python3 >/dev/null 2>&1; then
        verify_check "python3" pass "$(python3 --version 2>&1)"
        if python3 -c "import sqlite3" 2>/dev/null; then
            verify_check "python3 sqlite3 import" pass "ok"
        else
            verify_check "python3 sqlite3 import" fail "cannot import — Nudge skill will not work"
        fi
    else
        verify_check "python3" fail "not on PATH — Nudge skill + hook examples will not work"
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
        if python3 -c "import json, sys; json.load(sys.stdin)" < "$setj" 2>/dev/null; then
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

# --- Install items -----------------------------------------------------------

section "Installing skills"
skills_src="${REPO_ROOT}/skills"
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
    "${REPO_ROOT}/hooks/examples" \
    "${CLAUDE_DIR}/hooks/examples" \
    "hooks/examples" \
    "hooks/examples"

section "Installing CLAUDE.md starter template"
install_item \
    "${REPO_ROOT}/templates/CLAUDE.md.clayworks-template" \
    "${CLAUDE_DIR}/CLAUDE.md.clayworks-template" \
    "CLAUDE.md.clayworks-template" \
    "CLAUDE.md.clayworks-template"

section "Installing settings.example.json"
install_item \
    "${REPO_ROOT}/templates/settings.example.json" \
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
cat <<'EOF'
1. Restart Claude Code so it picks up new skills:
     close all CC sessions, then open a fresh one.

2. To use the CLAUDE.md starter template:
     cp ~/.claude/CLAUDE.md.clayworks-template ~/.claude/CLAUDE.md
     (back up any existing ~/.claude/CLAUDE.md first)
     then edit the <YOUR ...> placeholders.

3. To use the nudge skill (if installed):
     the skill auto-triggers when you mention a time
     ("stop me at 5pm", "remind me about standup at 9:55").
     For nudges to actually fire, wire the UserPromptSubmit hook -
     see ~/.claude/skills/clayworks-lite-nudge/SKILL.md.

4. To use a hook example:
     cp ~/.claude/hooks/examples/<event>.sh ~/.claude/hooks/<name>.sh
     customize, then register it in ~/.claude/settings.json (see the README
     inside the examples/ dir).

Verify the install:
     ls ~/.claude/skills/clayworks-lite-*/
EOF

echo
echo "${C_GREEN}Done.${C_RESET}"
