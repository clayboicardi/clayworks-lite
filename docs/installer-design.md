# Installer design — rationale

The LITE installers (`install.sh`, `install.ps1`) implement a specific model: backup-then-install, SHA-256 hash-diff for idempotency, symlink rejection, no editing of user-owned config files. This doc explains each choice and what was rejected.

## Core design constraints

LITE installs into `~/.claude/` — a directory that may contain:

- A user's customized `CLAUDE.md` (sacred — never touch)
- A user's `settings.json` with hooks/permissions/env (sacred — never touch)
- A user's custom hooks at `~/.claude/hooks/` (sacred — never touch the dir contents, only manage `hooks/examples/`)
- A user's own skills/agents/commands directories

The constraint: **make additions to this directory without altering anything the user already owns**. Plus: any altering of LITE-installed files must be *reversible*.

## Why backup-then-install

Before any LITE file is overwritten, the existing version is copied to `~/.claude/.clayworks-lite-backup/<timestamp>-<pid>/<relative-path>`.

This is belt-and-suspenders for two scenarios:

1. **User had a previous install of LITE** and customized one of the LITE-shipped files (e.g., edited `~/.claude/skills/clayworks-lite-nudge/SKILL.md` for personal taste). New version of LITE wants to overwrite. Without backup, the user's edits disappear silently.
2. **Bug in this installer mis-identifies a non-LITE file as LITE-shipped** and tries to overwrite. Should never happen given the hash-diff guard, but defense-in-depth.

The backup directory accumulates across installs. The uninstaller doesn't auto-delete it (preserving user's recovery option); the README explicitly notes users can `rm -rf ~/.claude/.clayworks-lite-backup` to purge.

## Why SHA-256 hash-diff for idempotency

Re-running the installer should be a no-op if nothing has changed. The check: compute SHA-256 of the source file/dir, SHA-256 of the destination, compare. Match → skip with "already installed and unchanged." Mismatch → backup + overwrite + report.

This was chosen over alternatives:

- **mtime comparison.** Rejected: clock skew across machines / filesystems would produce false positives. Plus, a user touch-modifying a file (no content change) would trigger spurious backups.
- **Size + mtime check.** Less accurate than hash-diff for the same complexity. Rejected.
- **No idempotency check (just always re-copy).** Simplest. Rejected because it generates noise on every re-run — the user can't tell "nothing changed" from "everything changed."
- **Per-file diff (e.g. `diff -q`).** Equivalent to hash-diff in outcome, more I/O on large trees. Hash-diff scales better.

The directory-hash function deserves a note: it walks the directory, finds all non-symlink files, sorts them by path under `LC_ALL=C` (byte-ordinal), concatenates `relpath:filehash` lines, and hashes that string. This makes the directory hash deterministic across machines as long as file contents are identical and the same files are present. PowerShell's equivalent uses `Sort-Object FullName` which is case-insensitive — leading to a known platform-divergence (documented in `install.ps1`'s comments) for directories with mixed-case file names. Operationally moot because each script compares src vs dest within its own platform; only matters if a cross-platform-cache scheme is later layered on top.

## Why reject symlinks in the source tree

The installers refuse to proceed if `find <repo-root> -type l` returns anything. Honest LITE source trees contain no symlinks; the check is invisible to non-malicious users.

The threat model:

- A user clones a tampered fork (typosquatted mirror, malicious PR merged into a fork they trusted)
- The fork's source tree contains `skills/clayworks-lite-evil/exfil -> ~/.ssh/id_ed25519`
- Under naive `cp -R`, the symlink is followed and the *target's contents* land in `~/.claude/skills/clayworks-lite-evil/exfil` as a regular file
- The exfil is now in a predictable user-readable location for any subsequent malicious skill, hook, sync tool, or backup tool to read

Mitigations layered in this installer:

1. **Pre-copy check rejects any symlink-containing source.** Loud fail with exit code 4.
2. **`cp -RP`** instead of `cp -R` (preserves symlinks as symlinks rather than dereferencing — belt-and-suspenders with #1).
3. **`path_hash()` excludes symlinks** (`find . -type f -not -type l`) so an attacker swapping symlink targets between hash and copy doesn't corrupt the idempotency check (TOCTOU defense).
4. **PowerShell equivalent** (`Test-NoSymlinksInSource`) handles SymbolicLink and Junction reparse points on Windows.

Discussion of alternatives:

- **Just allow symlinks; they're rare.** Rejected — the attack is realistic, the defense costs ~20 lines.
- **Allow symlinks but validate targets stay inside source tree.** More complex; harder to get right cross-platform. Rejected for simplicity (zero-symlinks is easier to validate than constrained-symlinks).
- **Sandbox the install entirely (e.g., chroot).** Overkill for the threat model. Rejected.

## Why no auto-edit of `settings.json`

The installer never modifies `~/.claude/settings.json`. The user wires LITE hooks themselves by editing the file (with `templates/settings.example.json` as reference).

This is a deliberate non-feature. Reasoning:

**`settings.json` is a user-owned JSON file with arbitrary structure.** Hook registration is one of many things that file holds — permissions, env vars, plugin lists, statusLine config, etc. An installer that edits the file has to:

1. Parse user's JSON (which may have comments if they use `jsonc`)
2. Identify the right insertion point
3. Merge with existing hooks (without duplicating, without removing user entries)
4. Preserve user's formatting + ordering preferences

Any of those four can go wrong silently. The blast radius of a corrupted `settings.json` is severe (CC may refuse to start, user loses their entire configuration).

**Alternative considered: ship a `settings.example.json` and let the user merge.** This is what LITE does. The user retains full control of their config; the trade-off is one extra adoption step (copy-paste a JSON block from the example into the live file).

**Alternative considered: ship an installer command that ASKS the user before each edit.** Better than auto-edit, worse than don't-edit. Adds installer-as-interactive-tool complexity; LITE's installer is otherwise non-interactive. Rejected for scope.

**Alternative considered: write a `~/.claude/settings.d/clayworks-lite.json` and rely on a settings-aggregator.** CC doesn't currently merge `settings.d/` files. Rejected because depending on an unannounced feature is fragile.

The uninstaller has the same constraint: it can't auto-remove LITE hook entries from a user's `settings.json` (same JSON-edit fragility). Prints a hint instead.

## Why pure ASCII in `install.ps1`

The PowerShell installer is ASCII-only — no em-dashes, no curly quotes, no Unicode. The bash installer has em-dashes in comments (LF + UTF-8 + no BOM works fine).

Why the constraint on PowerShell specifically?

**PowerShell expects either UTF-8-with-BOM or ASCII for non-ASCII files.** Without BOM, non-ASCII gets mis-interpreted (depending on the host's code page). The `PSScriptAnalyzer` rule `PSUseBOMForUnicodeEncodedFile` flags this.

LITE could ship `install.ps1` with a UTF-8 BOM. Two reasons it doesn't:

1. **BOM management is fragile across editors.** A contributor opening `install.ps1` in VS Code or Notepad++ may save-with-BOM-stripped without realizing; CI would then flag it. Net friction without lasting benefit.
2. **Pure ASCII works everywhere.** The em-dashes were stylistic, not semantic. Replacing them with `--` in comments costs nothing.

The bash side doesn't have the same constraint (LF + UTF-8 + no BOM is the default for `.sh`); em-dashes there are fine.

## Why `--uninstall` is hash-guarded

The uninstaller removes files only if `path_hash(src) == path_hash(dest)` — i.e., the installed file matches exactly what LITE ships. If the user customized the file (hash mismatch), it's left in place with a warning.

This preserves user edits. The user's customization of a LITE-shipped file is *legitimate* (they made it theirs); silent deletion would be a betrayal. The trade-off: a user who wants to fully uninstall has to manually remove customized files themselves, after deciding they don't want them.

The README documents this. The uninstaller prints it. Explicit.

## What's NOT in the installer

Deliberately omitted features:

- **Network calls.** Zero. No telemetry, no version check, no remote anything.
- **Privileged operations.** Never `sudo`, never asks for elevation. Refuses paths under `/etc`, `/usr`, etc. (P3 item, not yet shipped — would harden against fat-fingered `--claude-dir` usage).
- **Auto-update.** Users update by `git pull && ./install.sh`. The installer doesn't fetch new versions on its own.
- **Plugin marketplace registration.** Users run `/plugin marketplace add` themselves (documented in `templates/CLAUDE.md.clayworks-template` and the memory-routing SKILL.md). The installer doesn't shell out to `claude` CLI.
- **Settings.json mutation.** Covered above.

Each omission is a constraint that simplifies the threat model.

## When this design would be wrong

- **You're shipping LITE in a context where users WANT auto-edit of their config.** Some operator setups assume "the installer manages the config." LITE assumes the opposite (user manages config). If your distribution model has different defaults, the installer would need rework.
- **You're shipping LITE to a fleet that requires reproducible installs.** The current installer is idempotent but not declarative (no manifest, no state file). Larger-scale deployment would want a real config-management tool (Ansible, etc.) rather than this shell-script wrapper.
- **You're targeting Windows-native (no Git Bash, no WSL).** The PS installer covers this for the install path, but the `make test` target and most contributor commands assume bash. A truly Windows-first contributor workflow would need separate tooling.

## What this doc is NOT

- **Not the installer source** — `install.sh` and `install.ps1` carry the actual logic + inline comments. This doc explains the choices, not the code.
- **Not a security audit** — the symlink-rejection logic was added in response to a specific audit finding (Facet 4 P1-1, 2026-05-18). `SECURITY.md` is the policy doc; this is the design rationale.
