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
CLAUDE_DIR="${HOME}/.claude"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=1; shift ;;
        --claude-dir) CLAUDE_DIR="$2"; shift 2 ;;
        -h|--help)
            cat <<EOF
Clayworks LITE installer

Usage: ./install.sh [OPTIONS]

Options:
  --dry-run            Show what would change without writing
  --claude-dir PATH    Install root (default: ~/.claude)
  -h, --help           Show this message

Installs:
  skills/clayworks-lite-*/      -> \$CLAUDE_DIR/skills/
  hooks/examples/               -> \$CLAUDE_DIR/hooks/examples/
  templates/CLAUDE.md.*         -> \$CLAUDE_DIR/CLAUDE.md.clayworks-template

Your live \$CLAUDE_DIR/CLAUDE.md and \$CLAUDE_DIR/hooks/ are never touched.
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
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
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
path_hash() {
    local path="$1"
    if [[ ! -e "$path" ]]; then echo ""; return; fi
    if [[ -f "$path" ]]; then sha_file "$path"; return; fi
    if [[ -d "$path" ]]; then
        (
            cd "$path"
            find . -type f -print0 | LC_ALL=C sort -z | while IFS= read -r -d '' f; do
                printf '%s:%s\n' "${f#./}" "$(sha_file "$f")"
            done
        ) | sha_stdin
        return
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
            if [[ -d "$src" ]]; then cp -R "$src" "$dest"; else cp "$src" "$dest"; fi
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
        if [[ -d "$src" ]]; then cp -R "$src" "$dest"; else cp "$src" "$dest"; fi
    fi
    upd "${label}: differed from source -> backed up + reinstalled"
    UPDATED+=("$label")
}

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
