# Contributing to Clayworks LITE

Thanks for your interest. A few ground rules:

## What's appreciated

- Bug reports on `install.sh` / `install.ps1` failures
- Hook scaffolding examples I haven't covered
- Documentation improvements (typos, ambiguities, missing prereqs)
- Edge-case sharpening on the memory-routing decision tree

## What's not appreciated

- "Add [my plugin] to the baseline" — the LITE baseline is intentionally minimal
- "Make this work with [other AI tool]" — Clayworks LITE is specifically for Claude Code
- Feature requests without a concrete problem. "It would be cool if..." gets closed; "I hit X scenario and there's no good path because Y" gets considered

## Process

1. Open an issue first for anything non-trivial. Save us both time.
2. Small fixes (typos, etc.): PR directly is fine.
3. PRs should have a clear "before/after" or "why this" in the description.
4. License contributions under MIT (this repo's license). Implicit on submit.

## Code review

Codex is the sole bot reviewer. Gemini Code Assist used to auto-review here too, but Google sunset the consumer app: it blocked new org installs from 2026-06-18 and ended all review activity on 2026-07-17. I removed the `.gemini/` config after the sunset.

- **Codex** (`chatgpt-codex-connector`) reviews automatically when a PR opens, and on demand when you comment `@codex review`. It reaches the operator's review host over Tailscale.
- **The independent project-scoped Claude Code session is the second voice.** `/multi:diff-review` is an optional extra read.
- **A *missing* Codex review is not a clean review.** Codex silently no-fires when it cannot reach the review host. The usual cause: the host's Tailscale `accept-dns` is off, so its MagicDNS name fails to resolve. If a PR opens and no Codex review appears, treat it as **review absent**, not "review clean." To fix, enable accept-dns on the review host (`tailscale set --accept-dns=true`), then re-trigger with `@codex review`. The PR template's review checklist exists so this cannot lapse silently.

## Local development

To test installer changes against a throwaway target dir:

```bash
# Dry-run shows what would change without writing
./install.sh --dry-run --claude-dir /tmp/clayworks-test

# Live install
./install.sh --claude-dir /tmp/clayworks-test

# Re-run — should report every item as "already installed and unchanged"
./install.sh --claude-dir /tmp/clayworks-test

# Sanity-check the install
./install.sh --verify --claude-dir /tmp/clayworks-test

# Clean uninstall
./install.sh --uninstall --claude-dir /tmp/clayworks-test
```

Or just `make test` — runs the same loop and grep-asserts idempotency.

For plugin changes, validate the manifests, `hooks/hooks.json`, and skill frontmatter the way CI does:

```bash
claude plugin validate --strict ./plugin
claude plugin validate --strict .
claude plugin validate --strict ./plugin/skills
```

To try the plugin itself without installing it, run `claude --plugin-dir ./plugin` and check `/hooks` for the Nudge entry. Point `CLAYWORKS_NUDGE_DB` at a scratch file first so test alerts stay out of your real DB.

Before opening a PR, the [PR template](.github/PULL_REQUEST_TEMPLATE.md) lists the checklist (`shellcheck` on shell files, `PSScriptAnalyzer` on `install.ps1`, `claude plugin validate --strict`, CHANGELOG entry under `[Unreleased]`, `.gitattributes`-respecting line endings). CI runs these automatically on push, plus a Nudge add → check → ack round trip on ubuntu and windows.

## Commit conventions

The repo's commit history uses **imperative subject + em-dash + brief rationale**: `Add X — short why`. Bodies are paragraphs (not bullet-lists where avoidable), focused on *why* not *what*. No `Co-Authored-By` line. CHANGELOG.md gets an entry under `[Unreleased]` for any user-visible change.

## Style & review conventions

These are the conventions the reviewer applies. I ported them from the old Gemini style guide (removed after the Gemini Code Assist sunset) so they feed Codex directly.

**Voice**

- **First person, active voice on public surfaces.** Speak as the maintainer. Avoid passive constructions ("is documented as…", "are designed to…") — they break the maintainer voice. This rule is load-bearing: it is the point the reviewer flags most.
- Em-dash density at most 1 per 150 words.
- No marketing-speak. Reject: "revolutionize", "unleash", "transform", "seamless", "robust", "powerful", "next-gen", "best-in-class".
- No exclamation marks outside code blocks. No "no-code" label.

**Installer security**

- Symlink rejection at install time; fsmonitor mitigation present.
- No `curl | bash` style pipelines for install paths users execute.
- Permissions on installed files match expected umask.

**Hook scaffolding contract**

- Each hook example matches the current Claude Code contract for its event: real stdin field names, `exit 2` (never `exit 1`) for anything meant to block, plain-text stdout where Claude Code adds it to context, and JSON output only where the event needs structured control. No hand-rolled `<system-reminder>` wrappers; Claude Code wraps hook output itself.
- No hook script silently swallows errors. The one deliberate exception: `run-python.sh` exits 0 with no output when no Python exists, so an optional feature can't turn every prompt into a hook error (`--verify` reports the missing Python instead).

**Skill structure**

- `SKILL.md` frontmatter present and valid; kebab-case naming.
- Skills reference their own files through `${CLAUDE_SKILL_DIR}`, never a hard-coded install path, so they work under both the plugin cache and `~/.claude/skills/`.
- Skills keep user data (like the Nudge DB) outside the skill directory, which plugin updates replace.

**README accuracy**

- README claims must match installed behavior; quick-start commands work on a fresh clone.
- Version numbers in the README badge match `plugin/.claude-plugin/plugin.json` and the top-level `version` in `.claude-plugin/marketplace.json`. The plugin version lives only in `plugin.json`; Claude Code uses it over any version in the marketplace entry, so I don't set one there.

**Brand separation (MIT compliance + private-system isolation)**

- No internal-only project terms, hook names, daemon names, or `C:\` paths in shipped files.
- No references to paid-bundle internals. License headers correct where applicable.

**Python & shell discipline**

- `python3` invocation in docs and hook examples, never bare `python`. The one exception is `run-python.sh`, whose job is to fall back to `python` / `py -3` on Windows. Type hints on public surfaces. No shell-injection risk in any subprocess call.
- Bash scripts target bash (macOS/Linux, and Git Bash on Windows, which Claude Code uses to run hooks) and stay ShellCheck-clean. `install.ps1` targets Windows PowerShell 5.1+ (`#Requires -Version 5.1`) and also runs on PowerShell 7+; don't use PS 7-only syntax there. When PowerShell writes JSON or markdown, write UTF-8 without a BOM.
- No BOM on `.ps1`. Consistent line endings per file.

**Non-goals (do not nit)**

- Reformatting bulk operations; whitespace / trailing-newline nits (linters handle); section ordering in existing READMEs.

## Security issues

See [SECURITY.md](SECURITY.md) — do not file security bugs as public issues.

## Code of conduct

Short version: be a person. Engage in good faith. That's it.

Formal version: this project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Report Code of Conduct issues to **[clayhaworth1@gmail.com](mailto:clayhaworth1@gmail.com)** with subject `[clayworks-lite CoC]`.
