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
- Feature requests without a concrete problem — "it would be cool if..." gets closed; "I hit X scenario and there's no good path because Y" gets considered

## Process

1. Open an issue first for anything non-trivial. Save us both time.
2. Small fixes (typos, etc.): PR directly is fine.
3. PRs should have a clear "before/after" or "why this" in the description.
4. License contributions under MIT (this repo's license). Implicit on submit.

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

## Security issues

See [SECURITY.md](SECURITY.md) — do not file security bugs as public issues.

## Code of conduct

Short version: be a person. Engage in good faith. That's it.

Formal version: this project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Report Code of Conduct issues to **[clayhaworth1@gmail.com](mailto:clayhaworth1@gmail.com)** with subject `[clayworks-lite CoC]`.
