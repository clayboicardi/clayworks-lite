# clayworks-lite agent & reviewer guide

Conventions for AI agents and the bot reviewer (Codex). The full, authoritative version lives in [CONTRIBUTING.md](CONTRIBUTING.md). This file carries the load-bearing rules so the reviewer applies them even on a PR that doesn't touch `CONTRIBUTING.md`, because Codex auto-loads `AGENTS.md`.

## Voice (load-bearing)

Write in first person, active voice on public surfaces. Speak as the maintainer. Avoid passive constructions ("is documented as…", "are designed to…"); they break the maintainer voice. This is the rule the reviewer flags most, so treat it as a hard gate.

## Review

Codex is the sole bot reviewer. Google is sunsetting Gemini Code Assist: it ends all review activity on 2026-07-17. Codex reviews on PR-open and on `@codex review`, and it reaches the operator's review host over Tailscale. A missing Codex review is review-absent, not review-clean: if none appears, enable accept-dns on the review host (`tailscale set --accept-dns=true`), then re-trigger with `@codex review`.

For the full style, installer-security, hook, skill, README-accuracy, brand-separation, and language-discipline rules, read [CONTRIBUTING.md](CONTRIBUTING.md#style--review-conventions).
