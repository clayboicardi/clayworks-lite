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

Codex is the sole bot reviewer for this repo. (Gemini Code Assist used to auto-review here; Google is sunsetting it — new org installs blocked from 2026-06-18, all review activity ceases 2026-07-17.)

- **Codex** (`chatgpt-codex-connector`) reviews automatically when a PR opens, and on demand when you comment `@codex review`. It routes through Tailscale to the CLAY-MAE host.
- **The independent project-scoped Claude Code session is the second voice.** `/multi:diff-review` is an optional extra read.
- **A *missing* Codex review is not a clean review.** Codex silently no-fires when CLAY-MAE is unreachable — most often when the laptop's Tailscale `accept-dns` is off, so `clay-mae.tailb690b1.ts.net` doesn't resolve. If a PR opens and no Codex review appears, treat it as **review absent**, not "review clean." Fix: `tailscale set --accept-dns=true`, then re-trigger with `@codex review`. The PR template's review checklist exists so this can't lapse silently.

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

Before opening a PR, the [PR template](.github/PULL_REQUEST_TEMPLATE.md) lists the checklist (`shellcheck` on shell files, `PSScriptAnalyzer` on `install.ps1`, CHANGELOG entry under `[Unreleased]`, `.gitattributes`-respecting line endings). CI runs these automatically on push.

## Commit conventions

The repo's commit history uses **imperative subject + em-dash + brief rationale**: `Add X — short why`. Bodies are paragraphs (not bullet-lists where avoidable), focused on *why* not *what*. No `Co-Authored-By` line. CHANGELOG.md gets an entry under `[Unreleased]` for any user-visible change.

## Style & review conventions

These are the conventions the reviewer applies. Ported from `.gemini/styleguide.md` (deprecated; see banner there) so they survive Gemini's removal and feed Codex directly.

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

- All standard hook events covered correctly; hook outputs JSON where the contract requires JSON.
- No hook script silently swallows errors.

**Skill structure**

- `SKILL.md` frontmatter present and valid; kebab-case naming.
- Skills register their tool surface explicitly, no implicit globals.

**README accuracy**

- README claims must match installed behavior; quick-start commands work on a fresh clone.
- Version numbers in README match `package.json` / `pyproject.toml` / equivalents.

**Brand separation (MIT compliance + private-system isolation)**

- No internal-only project terms, hook names, daemon names, or `C:\` paths in shipped files.
- No references to paid-bundle internals. License headers correct where applicable.

**Python & shell discipline**

- `python3` invocation only, never bare `python`. Type hints on public surfaces. No shell-injection risk in any subprocess call.
- Bash scripts target POSIX-compatible shells unless otherwise declared; PowerShell targets PS 7+.
- No BOM on `.ps1`. Consistent line endings per file.

**Non-goals (do not nit)**

- Reformatting bulk operations; whitespace / trailing-newline nits (linters handle); section ordering in existing READMEs.

## Security issues

See [SECURITY.md](SECURITY.md) — do not file security bugs as public issues.

## Code of conduct

Short version: be a person. Engage in good faith. That's it.

Formal version: this project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Report Code of Conduct issues to **[clayhaworth1@gmail.com](mailto:clayhaworth1@gmail.com)** with subject `[clayworks-lite CoC]`.
