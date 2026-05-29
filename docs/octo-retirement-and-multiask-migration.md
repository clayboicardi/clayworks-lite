# Octo Retirement + Multi-Ask Migration — Adjustment Guide for Clayworks Repos

**Audience:** CC sessions (or Clay) working in `clayworks`, `clayworks-lite`, and `clayboicardi-com`.
**Purpose:** Tell each repo exactly what changed in the global environment (octo uninstalled, multi-ask stack replaced it, provider lineup changed) and exactly which files in that repo need adjusting to match.
**Authored:** 2026-05-29 by ClaydeClaw (from the multi-ask source-of-truth project + a live audit of all three repos).
**Source of truth for the changes:** `~/Projects/multi-ask/` and engram topic `architecture/quota-tracking-codex-gemini`.

---

## Part 1 — What changed globally (the facts)

### 1a. Octo was uninstalled (2026-05-23)
- The **`octo` plugin** (`octo@nyldn-plugins`, from `github.com/nyldn/claude-octopus`) was **deprecated and uninstalled** in Phase 4 of the multi-ask migration on **2026-05-23**.
- **All `/octo:*` skills are gone** (`/octo:research`, `/octo:debate`, `/octo:review`, etc.). Verified: no `~/.claude/skills/octo*` directories remain.
- The `nyldn-plugins` marketplace entry still sits in `~/.claude/settings.json:extraKnownMarketplaces` (url `github.com/nyldn/claude-octopus.git`) as a **1-week rollback window** only — it is not an endorsement to reinstall, and is being removed.
- Leftover local `.claude-octopus/` state directories are **runtime artifacts**, not config. They're safe to delete and are typically gitignored.

### 1b. Multi-ask replaced it
The `/octo:*` workflows were replaced by the **multi-ask stack** (`~/Projects/multi-ask/`):
- **Orchestrator:** `~/.claude/scripts/multi-ask.sh` — parallel fan-out across providers + optional Claude-synthesized output.
- **Provider wrappers:** `~/.claude/scripts/ask-{claude,codex,gemini,cerebras,ollama}.sh` (each stateless, headless, logged).
- **9 wrapper skills:** `/multi:research`, `/multi:prior-art`, `/multi:decide`, `/multi:falsify`, `/multi:diff-review`, `/multi:freshness-check`, `/multi:brainstorm`, `/multi:debug`, `/multi:doctor`. These are the `/octo:*` replacements.

### 1c. Provider lineup (current, 2026-05-29)
| Provider | Role | Transport | Notes |
|---|---|---|---|
| `claude` | synthesis + voice | `claude` CLI (Max OAuth) | synthesis pinned to `claude-opus-4-8[1m]` |
| `codex` | **PRIMARY** workhorse | `codex` CLI (ChatGPT Pro $100/mo OAuth) | heavy use |
| `gemini` | 3rd voice | `gemini` CLI **(old) — sunsets 2026-06-18** | migration to Antigravity CLI (`agy`) DEFERRED; see 2c |
| `cerebras` | opt-in 4th voice | HTTPS API (`api.cerebras.ai`) | **NEW**; free tier; default model `zai-glm-4.7` |
| `ollama` | local fallback | localhost:11434 | unchanged |
| ~~`perplexity`~~ | — | — | **evaluated and DROPPED** (Pro $20/mo no longer bundles Sonar API credits; API is pay-per-use) |

### 1d. Synthesis model pin
- Multi-ask synthesis now runs `claude-opus-4-8[1m]` (was `claude-opus-4-7`). Pinned via `CLAUDE_SYNTHESIS_MODEL` env in `~/.claude/settings.json` + wrapper defaults. Tracked in `~/Projects/multi-ask/docs/claude-synthesis-model-pin.md` (next review 2026-08-27).

### 1e. Quota tracking (new capability, not octo-related but part of the same cleanup)
- **onWatch** daemon at `localhost:9211` tracks codex/gemini/anthropic usage (dashboard = "Need A").
- **`~/.claude/hooks/cc-quota-status.sh`** UserPromptSubmit hook injects a `<quota-status>` line every prompt (live numbers = "Need B").
- Not shipped in any of these repos today; mentioned only so repo docs that describe the operator stack stay accurate.

---

## Part 2 — Shared rules (apply to ALL three repos)

1. **Gemini Code Assist ≠ Gemini CLI — do NOT touch `.gemini/styleguide.md`.** Every repo has a `.gemini/styleguide.md`; that configures **Gemini Code Assist** (the GitHub PR-review bot), which is a **separate product, decoupled from the Gemini CLI, and still in active use**. Leave all `.gemini/styleguide.md` files alone. Only Gemini *CLI* (`ask-gemini.sh`, `gemini` command) is affected by the sunset.

2. **Gemini CLI sunsets 2026-06-18.** Any shipped script or doc that invokes the `gemini` CLI (e.g., `ask-gemini.sh`) will stop working for Pro/Ultra/free tiers on that date. The migration target is **Antigravity CLI (`agy`)**, but that swap is **DEFERRED** (agy headless output capture is unsolved — see engram `discovery/agy-headless-capture-blocked`). Until it's solved, `ask-gemini.sh` keeps using the old `gemini` CLI. **Action for shipped artifacts:** add a dated caveat where the gemini bridge is documented; don't rip it out yet.

3. **`.claude-octopus/` directories are safe to delete locally.** They're octo runtime state. Confirm gitignored (clayworks already is) before assuming they're untracked.

4. **History stays as history.** `.remember/*`, `CHANGELOG.md` entries, and `.scratch/*` that mention octo/gemini/perplexity are append-only historical records — **do not rewrite them.** They correctly document what happened. Only fix *forward-facing* surfaces (templates users consume, live site copy, shipped READMEs).

---

## Part 3 — Per-repo action lists

### Repo A — `clayworks` (full / Pro product)

**Ships the bridges as a product component**, so changes here are product decisions, not just hygiene.

| File | Finding | Action |
|---|---|---|
| `components/multi-ai-bridges/scripts/ask-gemini.sh` | Shipped; uses old gemini CLI (sunsets 6/18) | Add dated sunset caveat to README/contract; plan agy migration once the global swap lands. Keep shipping for now. |
| `components/multi-ai-bridges/scripts/ask-ollama.sh` | Shipped; fine | No change. |
| `components/multi-ai-bridges/` (component scope) | Ships **only gemini + ollama** bridges | **DECISION (Clay):** does the Pro product add `ask-codex.sh` + `ask-cerebras.sh` to match the operator stack? If yes, port them from `~/.claude/scripts/` (strip personal paths). If no, document why the product bundles a narrower set. |
| `components/multi-ai-bridges/README.md` | Likely describes bridges and may reference octo for orchestration | Read it; if it points at `/octo:*` for orchestration, repoint to `/multi:*` or describe multi-ask.sh. Add the gemini-sunset caveat. |
| `.claude-octopus/` | Leftover octo runtime state | Already in `.gitignore` (line 29). Safe to `rm -rf` locally. No repo change. |
| `.gemini/styleguide.md` | Gemini **Code Assist** config | **LEAVE** (see Shared Rule 1). |
| `CHANGELOG.md`, `.remember/*` | Historical octo/gemini mentions | **LEAVE** (Shared Rule 4). |

### Repo B — `clayworks-lite` (open-source LITE base / plugin) — **HIGHEST PRIORITY**

**Ships octo *install instructions* to end users.** This is stale guidance pointing users at a retired plugin — fix first.

| File | Finding | Action |
|---|---|---|
| `plugin/templates/CLAUDE.md.clayworks-template:69-72` | Tells users: `**Multi-model orchestration:** /octo:research, /octo:debate, /octo:review. Install: /plugin marketplace add nyldn/claude-octopus; /plugin install octo@nyldn-plugins` | **REPLACE** with the multi-ask equivalent (or remove if LITE shouldn't bundle orchestration). Octo is retired; this install will give users a deprecated plugin. |
| `plugin/templates/CLAUDE.md.clayworks-template:67` | Documents `ask-gemini.sh` bridge | Keep; add gemini-CLI sunset caveat. |
| `plugin/templates/CLAUDE.md.clayworks-template:162` | "Multi-AI bridges — wired Gemini CLI + local Ollama" | Update provider description if LITE's framing should reflect the broader stack (or leave if LITE intentionally ships only gemini+ollama). |
| `plugin/templates/settings.example.json:58` | `_comment_plugins` names "Octo for multi-AI orchestration" | Remove/replace the Octo mention; point at multi-ask or drop. |
| `plugin/docs/upgrade-philosophy.md:62` | LITE template "names 3 (Engram, Honcho, Octo)" | Update the trio — Octo is retired. |
| `plugin/examples/full/CLAUDE.md:46` | "Available AI bridges:" section | Read + reconcile with the current provider lineup. |
| `.claude-plugin/marketplace.json`, `plugin/.claude-plugin/plugin.json` | Check for octo/nyldn marketplace refs | Grep + remove any octo marketplace dependency. |
| `.gemini/styleguide.md`, `.firecrawl/*`, `.remember/*`, `.scratch/*` | Code Assist config / cached web / history | **LEAVE.** |

### Repo C — `clayboicardi-com` (public landing site, Astro — **LIVE**)

**Public marketing claims are now inaccurate.** These render on the live site.

| File | Finding | Action |
|---|---|---|
| `src/data/acknowledgments.json` (Tooling group) | Live public credit: `nyldn … "Octo multi-AI orchestration; the bundle's routing pattern compounds with it nicely."` | **DECISION (Clay):** octo is retired. Options: (a) remove the entry, (b) keep as historical credit but reword to past tense ("influenced the routing pattern"), (c) replace with a self-credit for the multi-ask approach. Currently implies a live recommendation. |
| `src/data/whats-not-in-lite.json` | Live Pro-feature bullet: `"Multi-AI bridges (Gemini CLI + local Ollama integrations with logging, sandboxing, fallback)"` | **UPDATE** the provider list to reflect the real stack (Claude + Codex + Gemini + Cerebras + local Ollama). Outdated copy undersells the bundle. |
| `docs/landing-v1-plan.md:902,1266`, `docs/landing-v1-design.md:106`, `docs/landing-v2-design.md:389-390` | Internal design docs referencing octo:research, nyldn, "Gemini CLI + local Ollama" | Lower priority (internal). `landing-v1-plan.md:1266` carries the same nyldn/octo acknowledgment data that feeds the live `acknowledgments.json` — update together if you change the live credit. The `octo:research` mentions are historical process notes; leave. |
| `.gemini/styleguide.md` | Code Assist config | **LEAVE.** |
| After any `src/data/*.json` edit | Astro site | Rebuild + redeploy (`npm run build` → Cloudflare deploy via `wrangler.jsonc`). |

---

## Part 4 — Decisions for Clay (flagged, not auto-resolved)

These are product/brand calls the repos can't make mechanically:

1. **clayworks Pro bridge scope** — add `ask-codex.sh` + `ask-cerebras.sh` to the shipped `components/multi-ai-bridges/`, or keep it gemini+ollama and document the rationale?
2. **clayworks-lite orchestration story** — replace the octo-install block with a `/multi:*` install path, or drop bundled orchestration from LITE entirely (it's the *lite* tier)? Note: `/multi:*` skills live in `~/Projects/multi-ask/` — is that a public/installable thing LITE can point users to, or internal-only? If internal, LITE should describe the *pattern*, not an install command.
3. **clayboicardi-com octo credit** — remove, reword to historical, or replace with multi-ask self-credit?
4. **Gemini bridge sunset messaging** — once the `agy` swap lands (before 6/18), all three repos' gemini-bridge docs should flip from "Gemini CLI" to "Antigravity CLI (agy)". Track that as a follow-up tied to the agy work.

---

## Quick verification commands (per repo)

```bash
# Confirm what still references the retired tooling (run in each repo root)
grep -rniE "octo|nyldn/claude-octopus|/octo:" . \
  --include="*.md" --include="*.json" --include="*.sh" \
  | grep -vE "/\.git/|/node_modules/|/\.remember/|/\.firecrawl/|/\.scratch/|CHANGELOG"

# Gemini CLI (not Code Assist) references that face the 6/18 sunset
grep -rniE "ask-gemini\.sh|gemini CLI|gemini cli" . \
  --include="*.md" --include="*.json" --include="*.sh" \
  | grep -vE "/\.git/|/node_modules/|\.gemini/styleguide"
```

(Exclude `.remember/`, `.firecrawl/`, `.scratch/`, and `CHANGELOG.md` — those are history/cache and stay per Shared Rule 4.)
