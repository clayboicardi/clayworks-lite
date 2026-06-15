# clayworks-lite Style & Review Guide

> **Deprecated — retained for Gemini's remaining review window only.** Gemini Code Assist is being sunset (new org installs blocked 2026-06-18; all review activity ceases 2026-07-17). The authoritative style-and-review conventions now live in [`CONTRIBUTING.md`](../CONTRIBUTING.md#style--review-conventions); Codex is the sole bot reviewer going forward. Edit `CONTRIBUTING.md`; mirror any load-bearing change here only while Gemini still reviews. This file and `config.yaml` should be removed after the 2026-07-17 sunset.

Tells Gemini Code Assist what matters when reviewing changes to the open-source LITE base.

## Voice

- First person on public surfaces.
- Em-dash density at most 1 per 150 words.
- No marketing-speak. Reject: "revolutionize", "unleash", "transform", "seamless", "robust", "powerful", "next-gen", "best-in-class".
- No exclamation marks outside code blocks.
- No "no-code" label.

## Installer Security

- Symlink rejection at install time.
- fsmonitor mitigation present.
- No `curl | bash` style pipelines for install paths users execute.
- Permissions on installed files match expected umask.

## Hook Scaffolding Contract

- All standard hook events covered correctly.
- Hook outputs JSON where the contract requires JSON.
- No hook script silently swallows errors.

## Skill Structure

- SKILL.md frontmatter present and valid.
- Naming follows the kebab-case convention used elsewhere.
- Skills register their tool surface explicitly, no implicit globals.

## README Accuracy

- README claims must match installed behavior.
- Quick-start commands actually work on a fresh clone.
- Version numbers in README match `package.json` / `pyproject.toml` / equivalents.

## Brand Separation (MIT compliance + private-system isolation)

- No internal-only project terms, hook names, daemon names, or `C:\` paths in files that ship.
- No references to the paid-bundle internals.
- License headers correct where applicable.

## Python Discipline

- `python3` invocation only, never bare `python`.
- Type hints on public surfaces.
- No shell-injection risk in any subprocess call.

## Cross-Platform Shell Discipline

- Bash scripts target POSIX-compatible shells unless otherwise declared.
- PowerShell scripts target PS 7+.
- No BOM on `.ps1`. Consistent line endings per file.

## Non-Goals

- Reformatting bulk operations.
- Whitespace / trailing-newline nits (linters handle).
- Section ordering in existing READMEs.
