## What this PR does

<!-- One or two sentences. -->

## Why this earns inclusion

<!-- LITE is intentionally minimal at six components. Explain why this belongs
     here rather than as a user-side customization or a paid-bundle feature. -->

## Before / after

<!-- Concrete behavior change, or "no behavior change, refactor". -->

## Testing

- [ ] `./install.sh --dry-run --claude-dir /tmp/clayworks-test` shows expected output
- [ ] `./install.sh --claude-dir /tmp/clayworks-test` succeeds on a clean target dir
- [ ] Re-running `./install.sh --claude-dir /tmp/clayworks-test` shows "already installed and unchanged" for unchanged items (idempotency)
- [ ] (Windows) `.\install.ps1 -DryRun -ClaudeDir $env:TEMP\clayworks-test` shows expected output
- [ ] Any modified SKILL.md / hook example / template / SECURITY.md renders correctly on GitHub
- [ ] `CHANGELOG.md` updated under `[Unreleased]` with the change category (`### Added` / `### Fixed` / `### Changed` / `### Security`)
- [ ] If the PR touches shell scripts, `shellcheck` passes locally
- [ ] If the PR touches PowerShell, `Invoke-ScriptAnalyzer` shows no new warnings

## License

By submitting this PR I confirm my contribution is licensed under MIT (the
project's license — implicit on submit per CONTRIBUTING.md).
