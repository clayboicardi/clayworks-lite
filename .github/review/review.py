#!/usr/bin/env python3
"""On-demand PR review via the Claude Messages API.

Triggered by a PR comment such as:

    /review model=opus effort=xhigh focus=security max_tokens=48000
    Extra instructions for the reviewer go here, after the flags.

Runs in GitHub Actions (see .github/workflows/claude-review.yml) or locally:

    python .github/review/review.py --pr 67 --comment "/review model=haiku effort=low" --no-post
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
COMMENT_LIMIT = 60000  # GitHub caps comment bodies at 65536 characters
TASK_BUDGET_BETA = "task-budgets-2026-03-13"
BOT_LOGIN = "github-actions[bot]"  # the workflow's GITHUB_TOKEN identity; only its comments are touched
SCAN_MARKER = "<!-- claude-review:scan-notice -->"  # secret-scan notices: own marker, so they never collapse a review
FLAG_RE = re.compile(r"^([a-z_]+)=(\S+)$")
MODEL_ID_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]{0,60}$")  # also keeps the comment marker safe
KNOWN_FLAGS = {"model", "effort", "focus", "max_tokens", "scan"}


class UsageError(Exception):
    pass


class ReviewTimeout(BaseException):
    """Raised by the deadline alarm. BaseException so the SDK's retry loop (`except Exception`) can't swallow it."""


def arm_deadline(seconds: int) -> None:
    """Interrupt the run at `seconds` so a failure comment is posted before the workflow job is killed.

    SIGALRM exists on the Linux runner; where it doesn't (local Windows runs) the job timeout is the only bound.
    """
    if hasattr(signal, "SIGALRM"):
        def fire(signum, frame):
            raise ReviewTimeout()
        signal.signal(signal.SIGALRM, fire)
        signal.alarm(seconds)


def disarm_deadline() -> None:
    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)


# --------------------------------------------------------------------------- gh


def gh(*args: str, payload: dict | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["gh", *args],
        input=json.dumps(payload).encode("utf-8") if payload is not None else None,
        capture_output=True,  # bytes: text=True would turn a bare \r inside a line into a newline
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {stderr.strip()[:500]}")
    return stdout


def react(repo: str, comment_id: str | None, content: str) -> None:
    if not comment_id:
        return
    try:
        gh("api", "-X", "POST", f"repos/{repo}/issues/comments/{comment_id}/reactions",
           "-f", f"content={content}")
    except RuntimeError as e:  # a missing reaction must not fail the review, but must not be silent
        print(f"::warning::Could not add the {content} reaction: {e}", file=sys.stderr)


COLLAPSE_MUTATION = (
    "mutation($id: ID!) { minimizeComment(input: {subjectId: $id, classifier: OUTDATED}) "
    "{ minimizedComment { isMinimized } } }"
)
VISIBILITY_QUERY = "query($ids: [ID!]!) { nodes(ids: $ids) { ... on IssueComment { id isMinimized } } }"
MAX_COLLAPSE = 20  # collapse at most this many visible earlier comments per run, newest first
VISIBILITY_CHUNK = 100  # GitHub's nodes(ids:) limit per query


def still_visible(node_ids: list[str], limit: int = MAX_COLLAPSE) -> list[str]:
    """Of these comment node IDs (newest first), the ones GitHub has not already minimized, at most `limit`.

    The window applies to *visible* comments, not to raw history, so old visible ones are never starved
    by a long run of already-collapsed ones. One query per VISIBILITY_CHUNK ids, not one mutation each.
    """
    visible: list[str] = []
    for i in range(0, len(node_ids), VISIBILITY_CHUNK):
        args = ["api", "graphql", "-f", f"query={VISIBILITY_QUERY}"]
        for node_id in node_ids[i:i + VISIBILITY_CHUNK]:
            args += ["-f", f"ids[]={node_id}"]
        nodes = json.loads(gh(*args))["data"]["nodes"]
        visible += [n["id"] for n in nodes if n and not n.get("isMinimized")]
        if len(visible) >= limit:
            break
    return visible[:limit]


def post_review_comment(repo: str, pr: str, marker: str, body: str, collapse_previous: bool = True,
                        also_collapse: tuple = ()) -> None:
    """Post a NEW comment, then collapse this marker's earlier ones as outdated.

    A new comment (not an edit of an old one) is what wakes the desktop app's PR monitor, and it
    keeps each review next to the commits it covers. Collapsing the older ones keeps the PR tidy.
    It is best-effort end to end (finding the old comments included) and never fails the review.
    Error and usage notices pass collapse_previous=False so a transient failure never hides the
    last good review; the next successful review collapses them too.
    """
    body = f"{marker}\n{body}"
    if len(body) > COMMENT_LIMIT:
        body = body[:COMMENT_LIMIT] + "\n\n_(comment truncated to fit GitHub's size limit; full text is in the workflow log)_"
    previous: list[str] = []
    if collapse_previous:
        try:  # filter in Python, never in a jq expression built from commenter-controlled text
            pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments") or "[]")
            matches = [c["node_id"] for page in pages for c in page
                       if (c.get("user") or {}).get("login") == BOT_LOGIN
                       and (c.get("body") or "").startswith((marker, *also_collapse))]
            previous = still_visible(matches[::-1])  # newest first
        except Exception as e:  # noqa: BLE001 - cosmetic; the review below must still be posted
            print(f"::warning::Could not check earlier review comments before posting: {e}", file=sys.stderr)
    gh("api", "-X", "POST", f"repos/{repo}/issues/{pr}/comments", "--input", "-", payload={"body": body})
    for node_id in previous:
        try:
            gh("api", "graphql", "-f", f"id={node_id}", "-f", f"query={COLLAPSE_MUTATION}")
        except Exception as e:  # noqa: BLE001 - cosmetic; never fail a posted review
            # Stop at the first failure: a token that cannot minimize will not succeed on the rest either.
            print(f"::warning::Could not collapse an earlier review comment (skipping the rest): {e}", file=sys.stderr)
            break


# ------------------------------------------------------------------- parsing


def usage_text() -> str:
    d = CONFIG["defaults"]
    budget_text = ", ".join(f"{k} {v['max_tokens']:,}" for k, v in CONFIG["effort_budgets"].items())
    return (
        "**Usage:** `/review [model=...] [effort=...] [focus=...] [max_tokens=...]` "
        "then optional free-text instructions on the following lines.\n\n"
        f"- `model`: {', '.join(CONFIG['models'])} (default `{d['model']}`), or a full `claude-...` model ID\n"
        f"- `effort`: {', '.join(CONFIG['efforts'])} (default `{d['effort']}`)\n"
        f"- `focus`: {', '.join(available_focuses())} (default `{d['focus']}`)\n"
        f"- `scan`: on or off (default `{d['scan']}`). On refuses to send a diff that looks like it contains credentials\n"
        f"- `max_tokens`: hard output cap, integer up to {CONFIG['limits']['max_tokens_cap']}; thinking counts toward it. "
        f"Default depends on effort: {budget_text} (full `claude-...` IDs: at most "
        f"{CONFIG['limits']['custom_model_max_tokens']:,}). "
        f"Pacing (`task_budget`) needs at least "
        f"{CONFIG['limits']['task_budget_min'] + CONFIG['limits']['task_budget_headroom']:,}; "
        "an explicit `max_tokens=` also turns off the automatic retry, since you set the cap"
    )


def available_focuses() -> list[str]:
    return sorted(p.stem for p in (HERE / "prompts").glob("*.md"))


def parse_comment(body: str) -> tuple[dict, str]:
    lines = body.strip().splitlines()
    first = lines[0].split()
    if not first or first[0] != "/review":
        raise UsageError("Comment must start with `/review`.")
    opts = dict(CONFIG["defaults"])
    note_words: list[str] = []
    in_flags = True
    for tok in first[1:]:
        m = FLAG_RE.match(tok) if in_flags else None
        if m:
            key, val = m.groups()
            if key not in KNOWN_FLAGS:
                raise UsageError(f"Unknown option `{key}`.")
            opts[key] = val
        else:
            in_flags = False
            note_words.append(tok)
    note = " ".join(note_words)
    rest = "\n".join(lines[1:]).strip()
    note = "\n".join(x for x in (note, rest) if x)

    if opts["model"] in CONFIG["models"]:
        model_id = CONFIG["models"][opts["model"]]["id"]
        prices = CONFIG["models"][opts["model"]]
    elif MODEL_ID_RE.match(str(opts["model"])):
        model_id, prices = opts["model"], None
    else:
        raise UsageError(f"Unknown model `{opts['model']}`.")
    if opts["effort"] not in CONFIG["efforts"]:
        raise UsageError(f"Unknown effort `{opts['effort']}`.")
    if opts["focus"] not in available_focuses():
        raise UsageError(f"Unknown focus `{opts['focus']}`.")
    if opts["scan"] not in ("on", "off"):
        raise UsageError("`scan` must be `on` or `off`.")
    explicit_max = None
    if opts.get("max_tokens"):
        try:
            explicit_max = int(opts["max_tokens"])
        except ValueError:
            raise UsageError("`max_tokens` must be an integer.")
        if not 1024 <= explicit_max <= CONFIG["limits"]["max_tokens_cap"]:
            raise UsageError(f"`max_tokens` must be between 1024 and {CONFIG['limits']['max_tokens_cap']}.")

    parsed = {
        "model_key": opts["model"], "model_id": model_id, "prices": prices,
        "effort": opts["effort"], "focus": opts["focus"], "explicit_max": explicit_max, "scan": opts["scan"] == "on",
        "task_budget_ok": bool(prices and prices.get("task_budget")),
    }
    parsed["max_tokens"], parsed["task_budget"] = budgets(parsed, opts["effort"])
    return parsed, note


def budgets(opts: dict, effort: str) -> tuple[int, int | None]:
    """(hard max_tokens, task_budget or None) for an effort level.

    Adaptive thinking has no provable upper bound, so no fixed max_tokens can promise a
    review. Two layers instead: task_budget tells the model its ceiling so it paces itself
    and finishes, and max_tokens sits well above it as a backstop. Billing is for tokens
    actually generated, so the higher cap costs nothing unless it is used.
    """
    cfg = CONFIG["effort_budgets"][effort]
    default_cap = cfg["max_tokens"]
    if not opts["task_budget_ok"]:  # model ID not in the table: output limit unknown, stay conservative
        default_cap = min(default_cap, CONFIG["limits"]["custom_model_max_tokens"])
    max_tokens = opts["explicit_max"] or default_cap
    lim = CONFIG["limits"]
    task_budget = min(cfg["task_budget"], max(max_tokens // 2, lim["task_budget_min"]))
    if not opts["task_budget_ok"] or max_tokens < lim["task_budget_min"] + lim["task_budget_headroom"]:
        task_budget = None
    return max_tokens, task_budget


def estimate_cost(prices: dict | None, usages: list) -> float | None:
    """Approximate USD for the completed attempts, or None for models without a price table."""
    if not prices:
        return None
    usd = 0.0
    for u in usages:
        in_rate, out_rate = prices["input_per_mtok"], prices["output_per_mtok"]
        if u.input_tokens > prices.get("long_prompt_threshold_tokens", float("inf")):
            in_rate, out_rate = prices["long_input_per_mtok"], prices["long_output_per_mtok"]
        usd += (u.input_tokens * in_rate + u.output_tokens * out_rate) / 1e6
    return usd


def lower_effort(effort: str) -> str | None:
    i = CONFIG["efforts"].index(effort)
    return CONFIG["efforts"][i - 1] if i > 0 else None


def call_model(client: anthropic.Anthropic, opts: dict, effort: str, system: str, user: str):
    """One streamed request at the given effort. Returns (message, request_id)."""
    max_tokens, task_budget = budgets(opts, effort)
    kwargs: dict = dict(
        model=opts["model_id"],
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    try:
        if task_budget:
            kwargs["output_config"] = {"effort": effort, "task_budget": {"type": "tokens", "total": task_budget}}
            stream_cm = client.beta.messages.stream(betas=[TASK_BUDGET_BETA], **kwargs)
        else:
            stream_cm = client.messages.stream(**kwargs)
        with stream_cm as stream:
            msg = stream.get_final_message()
    except anthropic.BadRequestError as e:
        # A model that rejects task_budget still gets a review, just without pacing.
        # Covers the field itself or a retired/rejected beta header; anything else is re-raised.
        if task_budget and re.search(r"task[_\- ]?budget|anthropic-beta|\bbeta\b", e.message, re.I):
            print(f"::warning::{opts['model_id']} rejected task_budget; retrying without it: {e.message[:200]}",
                  file=sys.stderr)
            kwargs["output_config"] = {"effort": effort}
            with client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        else:
            raise
    return msg, stream.request_id or "n/a"


# ---------------------------------------------------------------------- diff


def diff_lines(text: str) -> list[str]:
    """Split on \\n only, so U+2028, \\x0b and similar inside a line cannot start a fake 'line' that escapes
    the scan or shifts line numbers. Trailing \\r (CRLF files) is dropped."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [ln.rstrip("\r") for ln in lines]


GIT_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, '"': 34}
GIT_FIELD_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\S+')


def unquote_git(token: str) -> str:
    """Undo Git's C-style quoting of a path (core.quotePath): \\303\\251 -> e-acute, \\t, \\\\, \\"."""
    if not (len(token) >= 2 and token[0] == token[-1] == '"'):
        return token
    body, out, i = token[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567":
                digits, j = "", i + 1
                while j < len(body) and len(digits) < 3 and body[j] in "01234567":
                    digits += body[j]
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i = j
                continue
            if nxt in GIT_ESCAPES:
                out.append(GIT_ESCAPES[nxt])
                i += 2
                continue
        out += ch.encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


def diff_git_path(header: str) -> str:
    """Destination path from a `diff --git` header line, quoted or not."""
    rest = header[len("diff --git "):].strip()
    if '"' in rest:
        fields = GIT_FIELD_RE.findall(rest)
        if len(fields) >= 2:
            new = unquote_git(fields[-1])
            return new[2:] if new.startswith("b/") else new
    m = re.match(r"a/(.*) b/(.*)", rest)
    return m.group(2) if m else rest


def split_diff(diff: str) -> list[tuple[str, str]]:
    """Return [(path, section_text)] for each file in a unified diff."""
    sections, current, path = [], [], None
    for line in re.findall(r"[^\n]*\n|[^\n]+", diff):
        if line.startswith("diff --git "):
            if current:
                sections.append((path, "".join(current)))
            current = [line]
            path = diff_git_path(line.strip())
        else:
            current.append(line)
    if current:
        sections.append((path, "".join(current)))
    return sections


def number_lines(section: str) -> str:
    """Prefix added/context lines with their new-file line number (L<n>|)."""
    out, new_ln = [], None
    for line in diff_lines(section):
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if m:
            new_ln = int(m.group(1))
            out.append(line)
        elif new_ln is None:
            out.append(line)
        elif line.startswith("-"):
            out.append(f"     | {line}")
        elif line.startswith("\\"):
            out.append(line)
        else:
            out.append(f"L{new_ln}| {line}")
            new_ln += 1
    return "\n".join(out) + "\n"


def is_excluded(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(os.path.basename(path), pat)
               for pat in CONFIG["exclude_paths"])


def build_diff(raw: str) -> tuple[str, list[str]]:
    kept, skipped = [], []
    for path, section in split_diff(raw):
        if is_excluded(path):
            skipped.append(path)
        else:
            kept.append(number_lines(section))
    return "".join(kept), skipped


# ------------------------------------------------------------- secret scan
# The diff, PR title/description and branch names are sent to the Anthropic API. Refuse to send anything
# that looks like a credential. EVERY line of every file that would be sent is scanned (added, removed and
# context lines are all transmitted), after excluding the files that are never sent (lockfiles, images...).
# `str =`, `Final[str] =`, `str | None =`, `string =`: what may sit between `NAME_KEY:` and the value in source files
ANNOTATION_SRC = (r"[A-Za-z_][A-Za-z0-9_.\[\]<>]{0,40}(?:\s*\|\s*[A-Za-z_][A-Za-z0-9_.\[\]<>]{0,40}){0,3}\s*=(?!=)\s*")


BLOCK_INDICATOR = r"[|>](?:[+\-][0-9]?|[0-9][+\-]?)?"  # YAML block scalar header: | > |- >+ |2- >2+ |-2 ...


class AssignedCredential:
    """A quoted assignment `name = "value"` (or `name: "value"`) whose NAME ends in api_key / secret / passwd /
    password / passphrase / pwd / pass / token, optionally followed by delimited words (AWS_SECRET_ACCESS_KEY, DATABASE_PASSWORD_PROD, mytoken)
    but not by glued letters (secretary), and whose VALUE is 20+ characters of [A-Za-z0-9_-+/=.].

    Linear time: the lookbehind starts a match only at the beginning of an identifier, so a long run such as
    `token_token_token_...` is consumed once instead of once per `token` inside it, and only the tail of the
    identifier is checked for the keyword.
    """
    ASSIGN = re.compile(r"(?<![A-Za-z0-9_\-])([A-Za-z0-9_\-]+)['\"]?\s*[:=]\s*(?:" + ANNOTATION_SRC + r")?"
                        r"(?:[rRbBuUfF]{1,2})?(['\"])([A-Za-z0-9_\-+/=.]{20,})\2")
    NAME_END = re.compile(r"(?:api[_-]?key|secret|passwd|password|passphrase|pwd|token|(?<![a-z0-9])pass)(?:[_\-][A-Za-z0-9]+)*$", re.I)

    def search(self, text: str):
        for m in self.ASSIGN.finditer(text):
            tail = self.NAME_END.search(m.group(1)[-200:])
            if tail and not metadata_name(tail.group()) and not exempt_value(m.group(3), m.group(2)):
                return m
        return None


# Source files (and Terraform/HCL, where `local.app_api_key` is a reference) hold expressions on the right of
# `NAME_KEY = ...`; config, env, shell, YAML and Dockerfile lines hold literal values (a password may contain any
# punctuation). The unquoted-value check is stricter in source files.
CODE_FILE_RE = re.compile(
    r"\.(?:jsx?|mjs|cjs|tsx?|py|rb|go|java|kts?|rs|php|cs|swift|c|h|cc|cpp|hpp|scala|lua|pl|vue|svelte|astro|dart|exs?|clj|tf|hcl|groovy|gvy|gradle|sol|zig|mm|hx)$|(?:^|/)Jenkinsfile[^/]*$",
    re.I)
WORDLIKE_SEGMENT_RE = re.compile(r"(?:[A-Z]+|[a-z]+|[A-Z][a-z]+)[0-9]{0,2}")
SCREAMING_RE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
SEGMENT_SPLIT_RE = re.compile(r"[_\-. ]+")
# Words that only ever appear in placeholders. A value is a placeholder only if EVERY one of its words is one of these
# (or a number / xxx), so a real passphrase that merely contains `here` or `example` is not exempt.
PLACEHOLDER_SEGMENTS = frozenset((
    "your api key secret token password passwd pass pwd here changeme change me replace with example placeholder sample "
    "dummy fake redacted todo insert enter value please in production prod dev test goes put real actual hidden private "
    "public the a an of for this that string text default none null empty unset required").split())
PLACEHOLDER_MASK_RE = re.compile(r"x{2,}|\*+", re.I)  # xxxxxxxx, ********
PLACEHOLDER_NUMBERLIKE_RE = re.compile(r"v?[0-9]+", re.I)  # v2, 123456: allowed next to a placeholder word, never alone
# `$VAR`, `${VAR}`, `${VAR:-default}`, `$(command)`, `{{ template }}`, `<placeholder>`
REF_TOKEN_RE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-+=?]([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)|\$\(([A-Za-z0-9_\-./]*)\)"
    r"|\{\{[A-Za-z0-9_.\-]*\}\}|<[^<>]+>")
REF_SEPARATORS_RE = re.compile(r"[\-_.:/@]*")
ANGLE_RE = re.compile(r"<[^<>]+>")
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^/@\s]+(?:/\S*)?")  # no user:password@ part
PATH_RE = re.compile(r"(?:\.{1,2}/|~/|/)?(?:[a-z0-9._\-]+/)+[a-z0-9._\-]*\.[a-z0-9]{1,6}")  # lowercase dirs + extension
SECRET_SHAPED_RUN_RE = re.compile(r"(?=[A-Za-z0-9_\-+]*[0-9])(?=[A-Za-z0-9_\-+]*[A-Za-z])[A-Za-z0-9_\-+]{16,}")
SECRET_SHAPED_SLASHY_RE = re.compile(r"(?=[A-Za-z0-9_\-+/]*[0-9])(?=[A-Za-z0-9_\-+/]*[A-Za-z])[A-Za-z0-9_\-+/]{16,}")
CREDENTIAL_PARAM_RE = re.compile(
    r"(?i)[?&#;](?:[A-Za-z0-9_.\-]*?[_.\-])??(?P<n>api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|key|secret"
    r"|password|passwd|pwd|sig|signature|auth|credential|bearer|jwt)=(?P<v>[^&#\s]{8,})")


METADATA_SUFFIXES = frozenset((
    "EXPIRY EXPIRES EXPIRE EXPIRATION TTL LIFETIME TIMEOUT SECONDS MINUTES HOURS DAYS FILE PATH DIR DIRECTORY LENGTH MIN MAX "
    "REQUIREMENTS POLICY RULES PATTERN REGEX STRENGTH URL URI ENDPOINT HEADER PREFIX NAME TYPE FORMAT ALGORITHM ALG COUNT "
    "ATTEMPTS RETRIES ENABLED DISABLED REQUIRED LOCATION SOURCE PROVIDER SCOPE SCOPES AUDIENCE ISSUER RE RX REGEXP").split())


CREDENTIAL_WORDS = frozenset("KEY SECRET TOKEN PASSWORD PASSWD PWD PASS PASSPHRASE".split())


def metadata_name(tail: str) -> bool:
    """`TOKEN_EXPIRY_POLICY`, `PASSWORD_MIN_LENGTH`, `API_KEY_FILE`: a name whose qualifiers say it describes a credential
    (when it expires, where it lives, how long it must be) rather than being one. Only the words AFTER the last credential
    keyword count, so `API_KEY_PROVIDER_TOKEN` (which ends in TOKEN again) is a credential. Unlisted words still count."""
    words = re.split(r"[_\-]", tail.upper())
    last = max((i for i, word in enumerate(words) if word in CREDENTIAL_WORDS), default=-1)
    return any(word in METADATA_SUFFIXES for word in words[last + 1:])


def member_path_like(value: str) -> bool:
    """A dotted member path such as `process.env.REACT_APP_API_KEY` or `settings.Database.Password`: only word
    characters and dots, two or more word segments, each an all-upper, all-lower or Capitalised word with at most
    a two-digit number. A random token's segments (`Zx9`, `Yw8Vu7Ts6Rq5Po4Nm3`) are not words."""
    if "." not in value or not re.fullmatch(r"[A-Za-z0-9_.]+", value):
        return False
    segments = [seg for seg in re.split(r"[_.]", value) if seg]
    return len(segments) >= 2 and all(WORDLIKE_SEGMENT_RE.fullmatch(seg) for seg in segments)


def placeholder_only(value: str) -> bool:
    """Every word of the value is a placeholder word (your_api_key_here, CHANGEME, YOUR-API-KEY-HERE-V2, xxxxxxxx).
    Whole-value on purpose: `correct_horse_here_staple` contains `here` but is a passphrase, so it is not exempt."""
    segments = [seg.lower() for seg in SEGMENT_SPLIT_RE.split(value) if seg]
    if not segments:
        return False

    def is_word(seg: str) -> bool:
        return seg in PLACEHOLDER_SEGMENTS or bool(PLACEHOLDER_MASK_RE.fullmatch(seg))

    # at least one real placeholder word (a purely numeric value is a PIN or a numeric key, not a placeholder)
    return any(is_word(seg) for seg in segments) and all(
        is_word(seg) or PLACEHOLDER_NUMBERLIKE_RE.fullmatch(seg) for seg in segments)


def is_reference(value: str, quote: str) -> bool:
    """The WHOLE value is a variable reference, or references joined only by separators (`${A}-${B}`).

    A literal fallback or literal text is never exempted: `${KEY:-Zx9...}` and `${PREFIX}-Zx9...` are scanned as
    values. Inside single quotes nothing expands, so only `<placeholder>` is a reference there."""
    if quote == "'":
        return bool(ANGLE_RE.fullmatch(value))
    pos, found = 0, False
    for m in REF_TOKEN_RE.finditer(value):
        fallback, command = m.group(2), m.group(4)
        if fallback and not (placeholder_only(fallback) or is_reference(fallback, quote)):
            return False
        if command is not None and not (placeholder_only(command) or re.fullmatch(r"[a-z][a-z0-9_\-]*", command)):
            return False
        if not REF_SEPARATORS_RE.fullmatch(value[pos:m.start()]):
            return False
        pos, found = m.end(), True
    return found and bool(REF_SEPARATORS_RE.fullmatch(value[pos:]))


def non_secret_literal(value: str) -> bool:
    """A public URL (no user:password@) or a path with directories and a file extension, as long as nothing inside it
    looks like a token (a 16+ character run with letters and digits, or a key/token/secret/password query parameter).
    The host of a URL is a name (`productioncluster2026.example.com`), so only its path and query are inspected for token
    shapes. A path must be lowercase directories plus an extension and a URL's path must not hold a token split by
    slashes, so a slash-bearing secret (`wJalr.../K7MD.../bPxR...`) is not mistaken for either."""
    if URL_RE.fullmatch(value):
        rest = value.split("://", 1)[1]
        tail = rest[len(re.split(r"[/?#]", rest, maxsplit=1)[0]):]  # everything after the host
        return not (SECRET_SHAPED_SLASHY_RE.search(tail) or SECRET_SHAPED_RUN_RE.search(tail)
                    or CREDENTIAL_PARAM_RE.search(value))
    if PATH_RE.fullmatch(value):
        return not (SECRET_SHAPED_RUN_RE.search(value) or CREDENTIAL_PARAM_RE.search(value))
    return False


RESOURCE_REF_RE = re.compile(
    r"(?i)(?:arn:[a-z0-9-]+:|(?:op|vault|ssm|aws-ssm|awssm|gcpsm|azurekv|secret|ref\+[a-z]+|file|env|keyring)://"
    r"|projects/[^/\s]+/secrets/|vault:|ssm:|secretsmanager:)\S*")


def exempt_value(value: str, quote: str, code: bool = False) -> bool:
    """Not a credential: a reference, a pure placeholder, a clean URL/path, or (UNQUOTED and in an EXPRESSION file only:
    source or Terraform) a CONSTANT_NAME or member path. A quoted value is a string literal, and a bare right-hand side
    in a `.env`, shell, YAML or INI file is a literal too, so `NAME_KEY=CORRECT_HORSE_BATTERY_STAPLE` and
    `NAME_KEY=correct.horse.battery.staple` there are candidates."""
    return (is_reference(value, quote) or placeholder_only(value) or non_secret_literal(value)
            or (bool(RESOURCE_REF_RE.fullmatch(value)) and not embedded_credential(value))
            or (code and not quote and bool(SCREAMING_RE.fullmatch(value) or member_path_like(value))))


FARG = r"""(?:[A-Za-z0-9_.\-]+|'[A-Za-z0-9_.\-]*'|"[A-Za-z0-9_.\-]*")"""  # a name, number or short quoted key inside {...}
FNAME = r"[A-Za-z0-9_.\-]+"
FSTRING_REF_RE = re.compile(
    r"(?:[\-_.:/@]*\{[A-Za-z_][A-Za-z0-9_.]*"
    r"(?:\[" + FARG + r"\]|\((?:" + FARG + r"(?:," + FNAME + r")*)?\))*"
    r"(?:![rsa])?(?::[A-Za-z0-9_.\-<>^=+,#%]*)?\})+[\-_.:/@]*")
USERINFO_RE = re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]*://[^/@\s:]*:(?P<v>[^/@\s]+)@")  # scheme://user:password@
GENERIC_PARAMS = frozenset("key token auth sig signature".split())  # too common to be a credential on length alone
CREDENTIAL_PREFIX_WORDS = frozenset((
    "secret private access api auth authorization client password passwd pwd credential credentials bearer jwt session signing "
    "encryption master admin license").split())


LOOKUP_CALLS = frozenset((
    "getenv get getsecret getparameter getparam read readsecret lookup param setting config env var variable fetch load "
    "getint getbool getboolean getfloat pop getattr getitem getconfig getsetting getoption getvalue getvar getenvvar "
    "readconfig readenv loadconfig").split())  # compared lowercase, without underscores
LOOKUP_VERBS = ("get", "read", "load", "fetch", "lookup", "find", "resolve")
LOOKUP_NOUNS = frozenset((
    "string str int integer long float double decimal bool boolean list dict map json yaml bytes text value values setting settings "
    "config configuration option options param params parameter parameters var vars variable variables env envvar environment "
    "secret secrets property properties prop attr attribute item entry key keys flag feature configvalue settingvalue "
    "environmentvariable secretvalue password passwords").split())
KEYRING_GETTER_RE = re.compile(
    r"(?i)(?:^|\.)_*(?:keyring|keychain|credential_?store|cred_?store)\.(?:get_?credentials?|get_?password)$")  # known stores


def is_lookup_call(callee: str) -> bool:
    """A call whose quoted argument is a lookup key: a known lookup (`getenv`, `config`, `param`...) or a lookup verb
    (get / read / load / fetch / lookup / find / resolve) followed by a getter noun (`get_string`, `getLong`,
    `load_setting`). `get_hashed_password('...')` consumes a value, so it is not one."""
    if KEYRING_GETTER_RE.search(callee):
        return True
    name = callee.rsplit(".", 1)[-1].replace("_", "").lower()
    return name in LOOKUP_CALLS or any(name.startswith(verb) and name[len(verb):] in LOOKUP_NOUNS for verb in LOOKUP_VERBS)


FSTRING_SIMPLE_REF_RE = re.compile(  # {name}, {a.b}, {a[0]}, {a!r}, {a:>10}: an interpolation that cannot hide a literal
    r"\{[A-Za-z_][A-Za-z0-9_.]*(?:\[[A-Za-z0-9_.\-]+\])*(?:![rsa])?(?::[A-Za-z0-9_.\-<>^=+,#%]*)?\}")
ROLE_WORDS = frozenset((
    "user users admin administrator service svc app application db database readonly readwrite read write reader writer owner "
    "root postgres mysql redis mongo api bot ci cd prod production dev development stage staging test testing qa backup replica "
    "primary account acct system sys etl batch worker job cron monitor metrics reporting analytics migration migrations deploy "
    "deployer operator ops sre support ro rw usr adm dba bi dw ml").split())


STRONG_ROLE_ABBREVIATIONS = frozenset("ro rw svc dba adm usr ops sre".split())  # unambiguous service-role abbreviations


ROLE_ALIASES = {  # abbreviations and full spellings of one role signal count once
    "adm": "admin", "administrator": "admin", "svc": "service", "usr": "user", "users": "user", "application": "app",
    "db": "database", "ro": "readonly", "rw": "readwrite", "prod": "production", "dev": "development", "stage": "staging",
    "acct": "account", "sys": "system"}


def plain_username(user: str) -> bool:
    """A userinfo username that is a role name, not a credential: empty, or an identifier of at most 40 characters that is
    not credential-shaped and either has fewer than four words (`svc-account-readonly`) or is MORE than half role words
    written as they are (`my_application_readonly_user`: 3 of 4), spanning at least two DISTINCT role signals (aliases such
    as admin / adm and service / svc count once) and corroborated by a full (4+ letter) role word or two distinct strong
    abbreviations. `correct_admin_admin_admin`, `correct_admin_adm_staple_admin` and `correct_ro_ro_ro` are kept."""
    if not user:
        return True
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\-]{0,39}", user) or SECRET_SHAPED_RUN_RE.search(user):
        return False
    words = re.split(r"[_.\-]", user.lower())
    if len(words) < 4:
        return True
    signals = [ROLE_ALIASES.get(word, word) for word in words if word in ROLE_WORDS]
    if len(signals) * 2 <= len(words) or len(set(signals)) < 2:
        return False
    return (any(len(word) >= 4 and word in ROLE_WORDS for word in words)
            or len({word for word in words if word in STRONG_ROLE_ABBREVIATIONS}) >= 2)  # no two share a signal


def interpolation_free(value: str) -> str:
    """An f-string with its simple `{name}` interpolations replaced by `x` (a reference, not a literal), and a userinfo
    whose password was one dropped when the username is a plain name, so `https://user:{db.pw}@host/db` is judged as
    `https://host/db` but a literal credential used as the username is kept (and flagged)."""
    def drop(m):
        user = m.group(2)
        plain = plain_username(user)
        return m.group(1) if plain else m.group(0)

    return re.sub(r"(://)([^/@\s:]*):x@", drop, FSTRING_SIMPLE_REF_RE.sub("x", value))


FSTRING_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\(\s*['\"]")  # a call with a quoted first argument inside {...}


def is_fstring_reference(value: str) -> bool:
    """`f"{settings.API_KEY}"`, `f"{settings['API_KEY']}"`, `f"{get_key()}"`, `f"{a.b}-{c}"`: the WHOLE f-string is
    interpolations (names, dotted paths, simple index or call suffixes) joined by separators. Text outside the braces,
    or a string literal inside them (`f"{'A1!x'}"`), is not a reference and is scanned as a value."""
    if not FSTRING_REF_RE.fullmatch(value):
        return False
    # a quoted argument is a lookup key only for a lookup: `{ApiKey('A1...')}` and `{str('A1...')}` hand over the value
    return all(is_lookup_call(m.group(1)) for m in FSTRING_CALL_RE.finditer(value))


def embedded_credential(value: str, fstring: bool = False) -> bool:
    """A credential inside the value of a metadata-named setting (`API_KEY_URL=https://x/cb?client_secret=...`,
    `TOKEN_ENDPOINT=https://user:password@host`): the name says the setting is about a credential, the value may not be.
    A generic parameter name (`key`, `token`, `auth`, `sig`, with no credential-bearing prefix: `secret_key` and
    `client_key` are explicit) needs a token-shaped value, not just eight characters (`?key=overview` is a search term)."""
    for m in CREDENTIAL_PARAM_RE.finditer(value):
        secret = m.group("v")
        if is_reference(secret, '"') or placeholder_only(secret) or (fstring and is_fstring_reference(secret)):
            continue
        prefix_words = re.split(r"[_.\-]+", value[m.start() + 1:m.start("n")].lower())
        generic = m.group("n").lower() in GENERIC_PARAMS and not any(word in CREDENTIAL_PREFIX_WORDS for word in prefix_words)
        if generic and not (SECRET_SHAPED_RUN_RE.search(secret) or len(secret) >= 24):
            continue
        return True
    for m in USERINFO_RE.finditer(value):
        secret = m.group("v")
        if not (is_reference(secret, '"') or placeholder_only(secret) or (fstring and is_fstring_reference(secret))):
            return True
    return False


METADATA_KWARGS = frozenset((
    "name username user login description desc label title id type kind url uri host hostname endpoint path file filename "
    "region scope audience issuer domain email account namespace version comment note tag tags source").split())
REGEX_CALL_RE = re.compile(r"(?:compile|RegExp|Regex|Pattern|regex)\(\s*[rRbBuUfF]{0,2}$")
OPERATOR_BEFORE_RE = re.compile(r"(?:[,=|?:+(\[]|(?:^|[^A-Za-z0-9_])(?:or|and|else))$")  # what precedes a value in an expression
# `SecretStr(`, `pydantic.SecretStr(`, `Password(`, `ConvertTo-SecureString(`: the argument IS the value, not a lookup key
# (`get_secret(` and `getSecret(` are lookups: the character before `secret` must not be a letter, digit or underscore)
VALUE_CONSTRUCTOR_RE = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9_])(?:secret\w*|secure\w*|password\w*|passphrase\w*|credential\w*|api_?key|token\w*|bearer\w*)\s*\($")
ADJACENT_RE = re.compile(r"\s*(?:\+\s*)?[rRbBuUfF]{0,2}(?=[\"'])")  # `"a" "b"` (implicit concatenation) and `"a" + "b"`


def adjacent_literals(text: str, pos: int, end: int, limit: int = 20):
    """(text of the string literals that directly follow `pos`, position after the last one). `"A1!correct-"
    "horse-battery-staple"` and `"a" + "b"` are ONE value at run time. A fragment with whitespace ends the chain."""
    joined = ""
    for _ in range(limit):
        m = ADJACENT_RE.match(text, pos)
        if not m or m.end() >= end:
            break
        quote, j = text[m.end()], m.end() + 1
        while j < end and text[j] != quote:
            j += 2 if text[j] == "\\" else 1
        fragment = text[m.end() + 1:j]
        if j >= end or re.search(r"\s", fragment):  # unclosed, or prose: not another piece of the same value
            break
        joined, pos = joined + fragment, j + 1
    return joined, pos


def escape_modes(text: str) -> tuple:
    """How to read backslashes in triple-quoted literals: as escapes (Python, Swift, Java) and, only when the text has a
    triple quote at all, as plain characters too (Kotlin and Scala raw strings)."""
    return (True, False) if ('"""' in text or "'''" in text) else (True,)


def nested_literals(text: str, pos: int, limit: int = 512, callees: bool = False, escapes: bool = True):
    """(literal, delimiter, is_fstring, mode) for each quoted literal in the expression that starts at `pos`, up to the
    end of the line or the first comma, semicolon or closing bracket at nesting depth 0 (so call arguments count but a
    sibling field of an object literal does not). Triple-quoted literals and adjacent literals are joined. `mode` is where
    the literal sits: "value" (any argument of a value constructor such as `SecretStr(`, keyword arguments included),
    "key" (the first argument of another call, or an index: usually a lookup key) or "default" (after `,` `=` `|` `?` `:`
    `+` or `or`/`and`/`else`: a fallback). A literal handed to a regex constructor is a pattern, and one that follows none
    of those is not a value. With `callees=True` a fifth item names the call a "key" literal is the first argument of."""
    end = min(len(text), pos + limit)
    window = text[pos:end]
    if '"' not in window and "'" not in window and "`" not in window:
        return  # no literal to find: the common case, and it keeps a long line of assignments cheap
    stack, i = [], pos  # one entry per open bracket: is it a value-constructor call?
    while i < end:
        ch = text[i]
        if ch == "\n":
            break
        if ch in "([{":
            if ch == "(":
                called = re.search(r"([A-Za-z_][A-Za-z0-9_.]*)\s*$", text[max(pos, i - 60):i])
                stack.append((bool(VALUE_CONSTRUCTOR_RE.search(text[max(pos, i - 40):i + 1])), called.group(1) if called else ""))
            else:
                stack.append((False, None))
        elif ch in ")]}":
            if not stack:
                break
            stack.pop()
        elif ch in ",;" and not stack:
            break
        elif ch in "\"'`":
            if text.startswith(ch * 3, i):  # a triple-quoted literal
                start, j = i + 3, i + 3
                while j < end and not text.startswith(ch * 3, j):
                    j += 2 if (escapes and text[j] == "\\") else 1  # Kotlin / Scala raw strings have no escapes
                j = min(j, end)
                close = min(j + 3, end)
            else:
                start, j = i + 1, i + 1
                while j < end and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                close = j + 1
            extra, after = adjacent_literals(text, close, end)
            before = text[max(pos, i - 40):i]
            if not REGEX_CALL_RE.search(before):
                prefix = re.search(r"[rRbBuUfF]{0,2}$", before)
                head = before[:prefix.start()].rstrip()
                mode, callee = None, None
                if not head and i - len(prefix.group()) <= pos:  # the literal (f"...", r"...") starts the expression
                    mode = "value"
                elif OPERATOR_BEFORE_RE.search(head):
                    kwarg = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*=$", head)
                    if kwarg and kwarg.group(1).lower() in METADATA_KWARGS:
                        mode = "metadata"  # `Credential(name="billing-service-api-key", ...)`: a label, not the value
                    elif stack and stack[-1][0]:
                        mode = "value"
                    elif head.endswith("("):
                        mode = "key"
                        called = re.search(r"([A-Za-z_][A-Za-z0-9_.]*)\($", head)
                        callee = called.group(1) if called else ""
                    else:
                        mode = "key" if head.endswith("[") else "default"
                if mode:
                    if callee is None and stack:
                        callee = stack[-1][1]  # the call this literal is an argument of
                    item = (text[start:j] + extra, ch, "f" in prefix.group().lower(), mode)
                    yield item + (callee,) if callees else item
            i = after - 1
        i += 1


def fstring_expressions(value: str, escapes: bool = True):
    """The expression inside each top-level `{...}` of an f-string body, with nested braces balanced, braces inside quoted
    (single, double or triple-quoted) strings ignored (`{os.getenv('K}', f'{x}')}`), and `{{` / `}}` escapes skipped.
    `escapes=False` reads a backslash inside a quoted string as a plain character (Kotlin / Scala raw strings)."""
    depth, start, quote, i, found = 0, 0, None, 0, []
    while i < len(value):
        ch = value[i]
        if depth == 0:
            if value[i:i + 2] in ("{{", "}}"):
                i += 2
                continue
            if ch == "{":
                depth, start = 1, i + 1
        elif quote:
            if ch == "\\" and escapes:
                i += 1
            elif value.startswith(quote, i):
                i += len(quote) - 1
                quote = None
        elif ch in "\"'":
            quote = ch * 3 if value.startswith(ch * 3, i) else ch
            i += len(quote) - 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                found.append(value[start:i])
        i += 1
    return found


PATH_STRONG_WORDS = frozenset((
    "path paths pathlib file files dir dirs directory folder open shutil fs glob copyfile copytree mkdir makedirs listdir abspath "
    "realpath relpath expanduser normpath").split())
PATH_AMBIGUOUS_OPS = frozenset((  # also collection methods; numbered filesystem APIs are listed by name (copy2, _stat64)
    "copy copy2 move rename remove unlink exists stat stat64 lstat64 chmod join resolve "
    # the whole documented MSVC _stat / _wstat family, hybrid widths included
    "stat32 stati64 stat32i64 stat64i32 wstat wstat32 wstat64 wstati64 wstat32i64 wstat64i32").split())
FS_RECEIVER_WORDS = frozenset("os nio io shutil fs filesystem".split())
# operations whose LATER arguments are paths too (shutil.copy(src, dst), Paths.get(a, b), os.path.join(a, b)), not a passphrase
PATH_ARG_LAST_WORDS = frozenset(
    "copy copy2 copyfile copytree move rename remove unlink join of get resolve symlink link relativize".split())


def callee_words(callee: str) -> list:
    """The lowercase components of a callee: dotted, snake_case, camelCase and acronym-bounded (`loadPEMFile` is load, pem, file).
    Digits are kept: `resolve2` is not `resolve` (numbered operations such as `copy2` are listed by name)."""
    spelled = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", callee))
    return [word for word in re.split(r"[._]+", spelled.lower()) if word]


def is_path_call(callee: str) -> bool:
    """A filesystem call (`Path.of`, `os.path.join`, `shutil.copy`, `Files.readString`, `loadPEMFile`, `File`, `open`): its
    callee has a path / file / directory word as a COMPLETE component, so `profile.encrypt` has none. An ambiguous operation
    (`remove`, `join`, `resolve`, `copy`, `move`...) counts when it is bare (`remove(...)`) or its receiver is a filesystem
    module (`os.remove`, `filesystem.resolve`), not for `credentials.remove(...)`."""
    words = callee_words(callee)
    if any(word in PATH_STRONG_WORDS for word in words):
        return True
    if not any(word in PATH_AMBIGUOUS_OPS for word in words):
        return False
    return len(words) == 1 or any(word in FS_RECEIVER_WORDS for word in words)


def takes_path_arguments(callee: str) -> bool:
    """A filesystem call whose later arguments are paths as well: it ends in a path operation (`shutil.copy`, `Paths.get`,
    `os.path.join`), unlike `ssh.openPrivateKey(path, passphrase)`."""
    return is_path_call(callee) and callee_words(callee)[-1] in PATH_ARG_LAST_WORDS


def secret_shaped_literal(value: str, delimiter: str, fstring: bool, mode: str = "default", callee: str | None = None) -> bool:
    """A literal inside a source expression that looks like a credential: 12+ characters without whitespace, not a
    reference / placeholder / public URL. In a value constructor (`SecretStr("...")`) or joined from adjacent literals
    it is judged like a top-level quoted value (anything else counts, even plain words). Elsewhere an `ENV_VAR_NAME` is
    a name too, and a fallback needs a digit or punctuation (so `"X-Api-Key-Header"` and `"service_api_key"` are names,
    `"A1!correct-horse"` is a value). The first argument of another call is usually a lookup key
    (`getenv("KEY")`, `get_secret("projects/p-1/secrets/k")`), so there only an unmistakably secret-like value counts:
    punctuation beyond `_-./:@`, or a 16+ character mix of upper, lower and digits. A fallback of plain lowercase words
    is not caught."""
    if mode == "metadata":  # a label is not a value, but a URL in it may carry one
        return embedded_credential(value, fstring)
    if fstring:
        if is_fstring_reference(value):
            return False
        for escapes in escape_modes(value):  # triple-quoted escapes differ by language: read the f-string both ways
            for expression in fstring_expressions(value, escapes):  # an interpolation can hide a literal: {str( 'A1...' )}
                for text, delimiter, is_f, mode, callee in nested_literals(expression, 0, callees=True, escapes=escapes):
                    if mode == "key" and callee and not is_lookup_call(callee):
                        mode = "value"  # the first argument of a call that is not a known lookup is the value itself
                    if secret_shaped_literal(text, delimiter, is_f, mode, callee):
                        return True
        value = interpolation_free(value)  # simple interpolations are references; what is left is judged
    if len(value) < 12 or re.search(r"\s", value):
        return False
    quote = "'" if delimiter == "'" else '"'
    reference = ((fstring and is_fstring_reference(value)) or is_reference(value, quote) or placeholder_only(value)
                 or non_secret_literal(value))
    if mode == "value":
        return not reference
    if reference or SCREAMING_RE.fullmatch(value):
        return False
    if WINDOWS_PATH_RE.fullmatch(value) and (
            (mode == "key" and (callee is None or is_lookup_call(callee) or is_path_call(callee)))
            or (mode == "default" and bool(callee) and takes_path_arguments(callee))):
        return False  # a path argument of a path / file call (Path.of, shutil.copy(src, dst)), never a fallback or a hashed value
    if mode == "key":
        return bool(re.search(r"[^A-Za-z0-9_\-./:@]", value)
                    or (len(value) >= 16 and re.search(r"[A-Z]", value) and re.search(r"[a-z]", value)
                        and re.search(r"[0-9]", value)))
    return bool(re.search(r"[0-9]", value) or re.search(r"[^A-Za-z0-9_\-.]", value))


_PATH = r"[A-Za-z0-9_.\-\\/+@~#]*"  # path characters (a quoted value may hold a #)
WORKDIR_VALUE_RE = re.compile(  # a path or batch variable, then a path only after a separator: what PWD / OLDPWD hold in a shell
    r"(?:/" + _PATH + r"|~(?:/" + _PATH + r")?|\.{1,2}(?:/" + _PATH + r")?"
    + r"|%[A-Za-z_][A-Za-z0-9_]*%(?:[\\/]" + _PATH + r")?|%~(?:dp|pd|p)[0-9]" + _PATH
    + r"|%~[a-z]*[0-9](?:[\\/]" + _PATH + r")?|[A-Za-z]:[\\/]" + _PATH + r"|\\\\" + _PATH + r")")
# a regex literal (`/^[a-z0-9]{20}$/`), not a Groovy slashy string
DESCRIPTOR_WORDS = frozenset((
    "FIELD NAME KEY HEADER ATTR ATTRIBUTE PARAM PARAMETER PROPERTY PROP LABEL COLUMN CLAIM SCOPE TYPE ID IDENTIFIER SLOT PATH ALIAS REF REFERENCE TAG SYMBOL").split())


def descriptor_name(name: str) -> bool:
    """A variable named like a descriptor (`TOKEN_KEY`, `secret_field`, `AUTH_HEADER`): its value may be the NAME of a
    credential field (`"access_token"`) rather than a credential. `DATABASE_PASSWORD` is not one."""
    return re.split(r"[_.\-]", name.upper())[-1] in DESCRIPTOR_WORDS
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[A-Za-z0-9_.\-\\/+@~#$ ]*")
_ALT = r"(?:[a-z][a-z0-9_]*|[A-Z][A-Z0-9_]*|[A-Z][a-z]+|[a-z]{2,}(?:[A-Z][a-z]+|[A-Z]{2,})+)"  # one alternative of a keyword / token-name alternation
REGEX_LIKE_RE = re.compile(
    r"^\^.*\$$|\\[dDwWsSbB.]|\[[^\]]*\]|\(\?|^\(?" + _ALT + r"(?:\|" + _ALT + r")+\)?$|\{\d+(?:,\d*)?\}|\.[*+]")
# a value that merely NAMES a credential field (`token_key = "access_token"`), not a credential
CREDENTIAL_FIELD_RE = re.compile(
    r"(?i)(?:api[_-]?key|api[_-]?secret|access[_-]?token|refresh[_-]?token|id[_-]?token|session[_-]?token|auth[_-]?token"
    r"|client[_-]?secret|secret[_-]?key|private[_-]?key|x-api-key|password|passwd|passphrase|token|secret|bearer|authorization)")


class EnvAssignment:
    """A credential-named variable and its value, in the syntaxes config and source files use:

    - `NAME_KEY=value`, `NAME_KEY: value` (YAML/JSON, optional closing quote on the name), `export NAME_KEY=value`,
      anywhere on a line (after a path separator, a bare carriage return, `VAR=1 cmd`...)
    - a type annotation before the value in source files: `NAME_KEY: str = "..."`
    - a YAML block scalar, `NAME_KEY: |` (or `>`, `|-`...), whose value is on the next line
    - a Dockerfile `ENV NAME_KEY value` (the space-separated form)

    The name is upper-case, ends in KEY/SECRET/TOKEN/PASSWORD/PASSWD optionally followed by delimited words
    (DATABASE_PASSWORD_PROD), and is not a metadata name (`metadata_name`). A *quoted* value (single, double, backtick or
    triple quotes, an optional Python prefix r/b/u/f, backslash escapes, no whitespace inside) is a literal in any file
    type, so 12+ characters of any punctuation count. An *unquoted* value is a literal in config/env files (12+
    non-space characters) but an expression in source files, and prose when it starts on the next line (16+ of
    [A-Za-z0-9_-+/] containing a digit). `exempt_value` decides what is never a credential. The name is matched as one
    identifier run (a lookbehind starts one match per identifier) and its tail checked in code, and values are read up
    to 512 characters, so work stays linear on hostile input such as `A_KEY=A_KEY=...`."""
    RUN = re.compile(r"(?<![A-Za-z0-9_\-$])(?<!\$\{)([A-Z][A-Z0-9_]*)['\"]?\s*(?:=|:(?=[\s'\"]))\s*")  # NAME=v  NAME: v  "NAME": v
    LOWER_RUN = re.compile(r"(?<![A-Za-z0-9_.\-$?&#])([A-Za-z][A-Za-z0-9_.\-]*)['\"]?\s*(?:=|:(?=[\s'\"]))\s*")  # password: v  db.pwd=v
    DOCKER_ENV = re.compile(r"(?<![A-Za-z0-9_\-])(?i:ENV)[ \t]+([A-Z][A-Z0-9_]*)[ \t]+")  # ENV NAME value
    ANNOTATION = re.compile(ANNOTATION_SRC)
    BLOCK_SCALAR = re.compile(BLOCK_INDICATOR)
    NEXT_LINE = re.compile(r"[ \t]*\n\s*")
    KEYWORD_TAIL = re.compile(r"(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|PASSPHRASE|(?<![A-Z0-9])PASS)(?:_[A-Z0-9]+)*$")
    QUOTED = re.compile(
        r"(?P<pfx>[rRbBuUfF]{1,2})?(?:(?P<q3>\"\"\"|''')(?P<v3>(?:[^\s\\]|\\.){0,512}?)(?P=q3)"
        r"|(?P<q>[\"'`])(?P<v>(?:[^\s\\]|\\.){0,512}?)(?P=q))")
    UNQUOTED = re.compile(r"[^\s'\"#;]{0,512}")
    SLASHY = re.compile(r"/([^\s/]{12,})/|\$/(\S{12,}?)/\$")  # Groovy slashy / dollar-slashy string literals
    STRICT = re.compile(r"(?=[A-Za-z0-9_\-+/]*[0-9])[A-Za-z0-9_\-+/]{16,}")

    def search(self, text: str, code: bool = False):
        for m in self.RUN.finditer(text):
            if self._credential(text, m.group(1), m.end(), ":" in m.group(), "\n" in m.group(), code):
                return m
        for m in self.DOCKER_ENV.finditer(text):
            if self._credential(text, m.group(1), m.end(), False, False, False):
                return m
        for m in self.LOWER_RUN.finditer(text):  # a lowercase key: a literal in a config file, a quoted literal in source
            if not m.group(1).isupper() and self._credential(text, m.group(1), m.end(), ":" in m.group(), "\n" in m.group(), code, True):
                return m
        return None

    def _credential(self, text: str, name: str, pos: int, colon: bool, joined: bool, code: bool, lower: bool = False) -> bool:
        tail = (AssignedCredential.NAME_END if lower else self.KEYWORD_TAIL).search(name[-200:])
        if not tail:
            return False
        metadata = metadata_name(tail.group())
        if colon and code:  # `NAME_KEY: str = "value"`: the annotation is not the value
            annotation = self.ANNOTATION.match(text, pos)
            if annotation:
                pos = annotation.end()
        literal = fstring = False
        quoted = self.QUOTED.match(text, pos)
        slashy = self.SLASHY.match(text, pos) if code and not quoted else None
        if slashy and REGEX_LIKE_RE.search(slashy.group(1) or slashy.group(2)):
            slashy = None  # a regex literal, not a string
        if quoted:
            if quoted.group("q3"):
                value, delimiter = quoted.group("v3"), quoted.group("q3")
            else:
                value, delimiter = quoted.group("v"), quoted.group("q")
            quote = "'" if delimiter[0] == "'" else '"'  # double quotes and backticks expand `$VAR`, single quotes do not
            fstring = "f" in (quoted.group("pfx") or "").lower()
            literal = True
            if code and not quoted.group("q3"):  # `"A1!correct-" "horse-battery-staple"`: adjacent literals are one value
                value += adjacent_literals(text, quoted.end(), min(len(text), quoted.end() + 512))[0]
        elif slashy:
            value, quote, literal = slashy.group(1) or slashy.group(2), '"', True
        else:
            value, quote = self.UNQUOTED.match(text, pos).group(), ""
            if colon and self.BLOCK_SCALAR.fullmatch(value):  # YAML `NAME_KEY: |` with the scalar on the next line
                following = self.NEXT_LINE.match(text, pos + len(value))
                if following:
                    value = self.UNQUOTED.match(text, following.end()).group()
                    literal = True  # block scalar content is literal text
        if lower and code and not literal:  # an unquoted lowercase value in source is an expression
            return False
        if descriptor_name(name) and CREDENTIAL_FIELD_RE.fullmatch(value):  # `token_key = "access_token"`: a field name
            return False
        if name in ("PWD", "OLDPWD") and WORKDIR_VALUE_RE.fullmatch(value):  # the shell's working directory, not a password
            return False
        if metadata:  # a setting about a credential: only a credential embedded in its value counts
            return embedded_credential(value, fstring) or (
                code and not literal and any(embedded_credential(lit[0], lit[2]) for lit in nested_literals(text, pos)))
        if code and not literal and any(secret_shaped_literal(*literal) for escapes in escape_modes(text[pos:pos + 512])
                                                 for literal in nested_literals(text, pos, callees=True, escapes=escapes)):
            return True  # `NAME_KEY = os.getenv("NAME_KEY", "fallback-literal")`
        if fstring and is_fstring_reference(value):
            return False
        if fstring:  # `{settings.X}` interpolations are references: judge what is left (`client_secret=x` is no credential)
            value = interpolation_free(value)
        if exempt_value(value, quote, code):
            return False
        if literal:
            return len(value) >= 12
        if code or joined:  # an expression in source, or prose wrapped after `NAME_KEY=`
            return self.STRICT.match(value) is not None
        if lower and ("(" in value or not re.search(r"[^A-Za-z_.\-]", value)):
            return False  # a lowercase key is weaker evidence than an ENV_NAME: a call, or plain words, are not enough
        return len(value) >= 12


ENV_ASSIGNMENT = EnvAssignment()


# Order matters: the first pattern that matches a line names it, so Anthropic keys (which the OpenAI pattern
# would also match) come first. Not covered: unquoted values in YAML/INI-style files (long identifiers would
# false-positive); `.env`-style `NAME_KEY=value` lines and quoted assignments are. The quoted-assignment
# pattern only accepts values made of letters, digits and _-+/=. (passwords with other punctuation are not
# matched: widening it would flag URLs and paths).
SECRET_PATTERNS = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API key", re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("AWS access key ID", re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9])(?:xox[abprs]-|xapp-|xoxe(?:\.xox[bp])?-)[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe live key", re.compile(r"(?<![A-Za-z0-9])[sr]k_live_[0-9a-zA-Z]{24,}")),
    ("Hardcoded credential", AssignedCredential()),
    ("Env-style credential", ENV_ASSIGNMENT),
]
# PEM bodies are 64-character base64 lines; a hunk that edits the middle of a key file has no BEGIN line.
KEY_FILE_RE = re.compile(r"(?:\.pem|\.key|\.p12|\.pfx|\.ppk|\.asc|\.pgp)$|(?:^|/)id_(?:rsa|dsa|ecdsa|ed25519)$", re.I)
BASE64_LINE_RE = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")
Finding = tuple[str, "int | None", str]


SLASH_COMMENT_RE = re.compile(
    r"(?:\.(?:jsx?|mjs|cjs|tsx?|java|kts?|go|rs|cs|swift|c|h|cc|cpp|hpp|scala|dart|vue|svelte|astro|groovy|gvy|gradle|proto"
    r"|sol|zig|jsonc|json5|mm|hx)|(?:^|/)Jenkinsfile[^/]*)$", re.I)  # `//` comments, no `#`


def comment_markers(path: str) -> str:
    """The comment markers of the file's language: "//" for C-like languages, "#//" for PHP and Terraform, "#" for everything else
    (Python's `//` is floor division, a shell `#` is a comment, a C-like `#` is not)."""
    if SLASH_COMMENT_RE.search(path):
        return "//"
    return "#//" if path.lower().endswith((".php", ".tf", ".tfvars", ".hcl")) else "#"


def strip_source_comment(line: str, markers: str = "#") -> str:
    """The line without a trailing comment: the delimiter is the first marker outside a string literal that starts the
    line, follows whitespace, or follows an opening bracket or comma (`f(# note`), so the comment text may contain quotes."""
    hash_ok, slash_ok = "#" in markers, "//" in markers
    quote, i = None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ((hash_ok and ch == "#") or (slash_ok and line.startswith("//", i))) and (
                i == 0 or line[i - 1].isspace() or line[i - 1] in "([{,;"):
            return line[:i].rstrip()
        i += 1
    return line


class MultiLine:
    """Constructs that span lines. `feed` takes one content line at a time (state resets at each hunk) and returns extra
    strings to scan with the line:

    - a YAML block scalar, `NAME_KEY: |` (or `>`, `|-`, `|2-`...): every following blank line or line indented past the
      key is the value
    - a triple-quoted string opened at the end of an assignment line: every following line up to the closing delimiter
    - an assignment whose line ends with an open parenthesis (`NAME = (`, `NAME = os.getenv(`): the lines up to the
      closing parenthesis, joined (so adjacent literals are one value and a fallback argument stays with its name)
    - a trailing backslash (Dockerfile `ENV NAME_KEY` then the value on the next line, shell `export NAME_KEY=`): the
      continued lines joined into one logical line"""
    BLOCK_HEADER = re.compile(r"(?<![A-Za-z0-9_.\-$])[A-Za-z][A-Za-z0-9_.\-]*['\"]?\s*:\s*" + BLOCK_INDICATOR + r"\s*(?:#.*)?$")
    MAX_PAREN = 1000
    TRIPLE_OPEN = re.compile(r"[:=]\s*(?:[rRbBuUfF]{1,2})?(\"\"\"|''')\s*$")
    MAX_LINES = 200  # a construct that never closes stops being followed after this many lines
    MAX_CARRY = 300  # only the tail of a continued line is carried: a name and its value are on adjacent lines

    def __init__(self, comments: str = "#"):
        self.comments = comments  # the comment markers of the file's language: "#", "//" or "#//"
        self.block = None  # (indent, header line) inside a block scalar
        self.triple = None  # (delimiter, header line) inside a triple-quoted string
        self.paren = None  # (header line, open depth, fragments so far) inside a parenthesised expression
        self.carry = ""  # the logical line so far while a trailing backslash continues it
        self.lines = 0

    @staticmethod
    def opens_assigned_call(line: str) -> bool:
        """The line ends with an open parenthesis and contains an assignment (`=` that is not part of `==`, `!=`, `<=`,
        `>=`, `:=`, or a YAML / annotation colon), not a comparison."""
        return line.rstrip().endswith("(") and bool(re.search(r"(?<![=!<>:])=(?!=)|:(?=\s)", line))

    def feed(self, line: str) -> list[str]:
        extra = []
        logical = line
        if self.carry:
            logical = self.carry + " " + line.lstrip()
            extra.append(logical)
        body = logical.rstrip()
        self.carry = body[:-1].rstrip()[-self.MAX_CARRY:] if body.endswith("\\") else ""
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if self.block is not None:
            block_indent, header = self.block
            if not stripped or indent > block_indent:
                self.lines += 1
                if stripped:
                    extra.append(header + "\n" + line)
                if self.lines > self.MAX_LINES:
                    self.block = None
                return extra  # scalar text is never itself a header
            self.block = None
        if self.triple is not None:
            delimiter, header = self.triple
            self.lines += 1
            if stripped:
                extra.append(header + stripped + delimiter)
            if delimiter in re.sub(r"\\.", "", line) or self.lines > self.MAX_LINES:  # an escaped delimiter is content
                self.triple = None
            return extra
        if self.paren is not None:
            header, depth, buffer = self.paren
            self.lines += 1
            fragment = strip_source_comment(stripped, self.comments)
            plain = re.sub(r"\"[^\"]*\"|'[^']*'", "", fragment)
            depth += plain.count("(") - plain.count(")")
            buffer = (buffer + " " + fragment).strip()
            if '"' in fragment or "'" in fragment:  # only a line that adds a literal can complete a credential
                extra.append(header + " " + buffer)
            keep = depth > 0 and self.lines <= self.MAX_LINES and len(buffer) <= self.MAX_PAREN
            self.paren = (header, depth, buffer) if keep else None
            return extra
        header = self.BLOCK_HEADER.search(line)
        if header:  # the key's own column: after the dash of a YAML sequence entry
            self.block, self.lines = (header.start(), stripped), 0
        elif self.opens_assigned_call(strip_source_comment(line, self.comments)):  # `NAME = (` or `NAME = os.getenv(  # note`
            opener = strip_source_comment(line, self.comments).rstrip()
            plain = re.sub(r"\"[^\"]*\"|'[^']*'", "", opener)
            depth = plain.count("(") - plain.count(")")
            if depth > 0:
                self.paren, self.lines = (opener, depth, ""), 0
        else:
            opened = self.TRIPLE_OPEN.search(line)
            if opened:
                self.triple, self.lines = (opened.group(1), line.rstrip()), 0
        return extra


def secret_name(text: str, code: bool = False) -> str | None:
    """Name of the first credential pattern found in `text`, or None. `code=True`: a source-file line."""
    for name, pattern in SECRET_PATTERNS:
        if (pattern.search(text, code) if pattern is ENV_ASSIGNMENT else pattern.search(text)):
            return name
    return None


def file_secret(path: str, text: str, code: bool | None = None) -> str | None:
    """Credential name for a line of `path`. Content lines are judged by the file type; diff header and hunk header
    lines pass code=False (a path in a header is literal text, not an expression)."""
    name = secret_name(text, code=bool(CODE_FILE_RE.search(path)) if code is None else code)
    if not name and KEY_FILE_RE.search(path) and BASE64_LINE_RE.fullmatch(text.strip()):
        name = "Key material in a key file"
    return name


PATH_LABEL = "a file path or header line in the diff"


def scan_for_secrets(raw_diff: str, texts=()) -> list[Finding]:
    """[(where, line, pattern name)] for every sent line that looks like a credential.

    `texts` are extra (label, text) strings that also go into the request (PR title, description, each branch
    name, omitted file names, the /review note). Values are never returned, and a path that itself holds a
    credential is reported with a generic label, so a finding can be posted publicly without repeating a secret.
    Each content line is also checked joined to the line before it, so `"api_key":` followed by `"value"` on
    the next line is caught.
    """
    findings: list[Finding] = []
    for label, text in texts:
        prev_line, ctx = None, MultiLine()
        for text_line in diff_lines(text or ""):
            extras = ctx.feed(text_line)
            name = secret_name(text_line)
            if not name and prev_line is not None:  # a name on one line, its value on the next
                name = secret_name(prev_line + "\n" + text_line)
            name = name or next(filter(None, map(secret_name, extras)), None)  # block scalar, triple quotes, continuation
            if name:
                findings.append((label, None, name))
                break
            prev_line = text_line
    for path, section in split_diff(raw_diff):
        if is_excluded(path):
            continue  # not sent (its name is scanned via `texts`, since the prompt lists omitted files)
        path_name = secret_name(path)
        where = PATH_LABEL if path_name else path
        if path_name and (PATH_LABEL, None, path_name) not in findings:
            findings.append((PATH_LABEL, None, path_name))  # the path is in every header line that is sent
        new_ln = None
        markers = comment_markers(path)
        sides, prev = {"old": MultiLine(markers), "new": MultiLine(markers)}, {"old": (None, None), "new": (None, None)}
        for line in diff_lines(section):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                new_ln = int(m.group(1))
                sides, prev = {"old": MultiLine(markers), "new": MultiLine(markers)}, {"old": (None, None), "new": (None, None)}
                name = file_secret(path, line, code=False)  # the hunk header's trailing function context is sent too
                if name:
                    findings.append((where, None, name))
                continue
            if new_ln is None:  # file header lines before the first hunk
                name = file_secret(path, line, code=False)
                header = (PATH_LABEL, None, name)
                if name and header not in findings:  # the path may hold the secret: do not echo it; report once
                    findings.append(header)
                continue
            if line.startswith("\\"):
                continue
            # an unprefixed fragment (should not occur once \r is preserved) keeps its first character
            content = line[1:] if line[:1] in (" ", "+", "-") else line
            # a context line belongs to both sides of the hunk, a removed line to the old side, an added line to the new one
            touched = ("old",) if line.startswith("-") else ("new",) if line.startswith("+") else ("old", "new")
            is_code = bool(CODE_FILE_RE.search(path))
            extras = list(dict.fromkeys(extra for side in touched for extra in sides[side].feed(content)))
            name = file_secret(path, content)
            for side in touched:  # a name on one line, its quoted value on the next (on the same side of the diff)
                prev_content, prev_name = prev[side]
                if not name and prev_content is not None and not prev_name:
                    name = secret_name(prev_content + "\n" + content, code=is_code)
            if not name:  # a block scalar, a triple-quoted string or a backslash-continued line spanning several lines
                name = next(filter(None, (secret_name(extra, code=is_code) for extra in extras)), None)
            for side in touched:
                prev[side] = (content, name)
            if line.startswith("-"):  # removed lines are sent to the API as well
                if name:
                    findings.append((f"{where} (removed line)", None, name))
                continue
            if name:  # added ("+") or context (" ") line
                findings.append((where, new_ln, name))
            new_ln += 1
    return findings


def secret_notice(findings: list[Finding]) -> str:
    def safe(where: str) -> str:  # the path is attacker-controlled: keep it inside its code span
        return re.sub(r"[`\r\n]", "'", where)

    shown = findings[:20]
    lines = [f"- `{safe(where)}{':' + str(line) if line is not None else ''}`: {name}" for where, line, name in shown]
    if len(findings) > len(shown):
        lines.append(f"- ...and {len(findings) - len(shown)} more")
    return (
        "**Review not sent: this PR looks like it contains credentials.** Nothing was sent to the Anthropic API. "
        "Added, removed and unchanged context lines are all sent in a review, so all of them are scanned.\n\n"
        + "\n".join(lines)
        + "\n\nThese values are already in this PR on GitHub, so rotate them even if you remove them from the diff. "
        "If they are false positives (fixtures, placeholders), re-run with `/review scan=off` to send it anyway."
    )


# ---------------------------------------------------------------------- main


def run_review(args: argparse.Namespace) -> int:
    repo = args.repo or os.environ.get("REPO", "")
    pr = str(args.pr or os.environ.get("PR_NUMBER", ""))
    comment_id = os.environ.get("COMMENT_ID")
    body = args.comment if args.comment is not None else os.environ.get("COMMENT_BODY", "")
    post = not args.no_post
    started, deadline = time.monotonic(), CONFIG["limits"]["deadline_seconds"]
    if not pr:
        print("PR number required", file=sys.stderr)
        return 2
    repo_flag = ["--repo", repo] if repo else []

    try:
        opts, note = parse_comment(body)
    except UsageError as e:
        text = f"Couldn't run the review: {e}\n\n{usage_text()}"
        print(text)
        if post:
            post_review_comment(repo, pr, "<!-- claude-review:usage -->", text)  # collapses only older usage notices
            react(repo, comment_id, "confused")
        return 1

    # The 👀 acknowledgement is added by the workflow's first step, not here.

    usages: list = []  # completed attempts; read by the timeout handler
    marker = f"<!-- claude-review:{opts['model_key']}:{opts['focus']} -->"
    try:
        meta = json.loads(gh("pr", "view", pr, *repo_flag, "--json",
                             "title,body,baseRefName,headRefName,additions,deletions,changedFiles"))
        raw_diff = gh("pr", "diff", pr, *repo_flag)
        diff, skipped = build_diff(raw_diff)
        # GitHub caps PR diffs (300 files); a short diff must not pass as a complete one.
        files_seen = len(split_diff(raw_diff))
        incomplete = ""
        if files_seen < meta["changedFiles"]:
            incomplete = (f"Only {files_seen} of {meta['changedFiles']} changed files were available from GitHub "
                          "(PR diff limit). Files beyond the limit were NOT reviewed.")
        if len(diff) > CONFIG["limits"]["max_diff_chars"]:
            msg = (f"This diff is {len(diff):,} characters after exclusions, over the "
                   f"{CONFIG['limits']['max_diff_chars']:,} limit. Nothing was sent to the API. "
                   "Split the PR, or raise `limits.max_diff_chars` in `.github/review/config.json`.")
            print(msg)
            if post:
                post_review_comment(repo, pr, marker, msg, collapse_previous=False)
                react(repo, comment_id, "confused")
            return 1

        if opts["scan"]:
            findings = scan_for_secrets(raw_diff, [
                ("PR title", meta["title"]), ("PR description", meta["body"] or ""),
                ("branch name", meta["headRefName"]), ("branch name", meta["baseRefName"]),
                ("review comment note", note),
                *[(PATH_LABEL, omitted) for omitted in skipped]])
            if findings:
                notice = secret_notice(findings)
                print(notice)
                if post:
                    # own marker: each new notice collapses the previous *notice*, never a review, so a remediation
                    # PR that keeps tripping the scan does not stack up notices
                    post_review_comment(repo, pr, SCAN_MARKER, notice)
                    react(repo, comment_id, "confused")
                return 1

        system = (HERE / "prompts" / f"{opts['focus']}.md").read_text(encoding="utf-8")
        system += "\n\n" + (HERE / "context.md").read_text(encoding="utf-8")
        user = (
            f"PR title: {meta['title']}\n"
            f"Branches: {meta['headRefName']} -> {meta['baseRefName']}\n"
            f"Size: +{meta['additions']} -{meta['deletions']} across {meta['changedFiles']} files\n"
            f"Files omitted from the diff (lockfiles/binaries/generated): {', '.join(skipped) or 'none'}\n\n"
            f"PR description:\n<pr_description>\n{meta['body'] or '(none)'}\n</pr_description>\n\n"
            f"<diff>\n{diff}</diff>\n"
        )
        if incomplete:
            user += f"\nNote: {incomplete} Say so in your Verdict.\n"
        if note:
            user += f"\nAdditional instructions from the repository owner:\n{note}\n"

        if args.dry_run:
            print(f"model={opts['model_id']} effort={opts['effort']} focus={opts['focus']} "
                  f"max_tokens={opts['max_tokens']}\nsystem chars={len(system)} user chars={len(user)}")
            print(user[:3000])
            return 0

        client = anthropic.Anthropic()
        effort = opts["effort"]
        arm_deadline(max(1, int(deadline - (time.monotonic() - started))))
        msg, request_id = call_model(client, opts, effort, system, user)
        usages.append(msg.usage)
        text = "".join(b.text for b in msg.content if b.type == "text").strip()

        # Safety net: thinking ate the whole budget and nothing was written. Retry once one
        # effort level lower so a review always lands; both attempts' cost is reported.
        retried_from = None
        lower = lower_effort(effort)
        time_left = deadline - (time.monotonic() - started)
        # An explicit max_tokens= is the caller capping spend, so it is never doubled by a retry.
        if (msg.stop_reason == "max_tokens" and not text and lower and opts["explicit_max"] is None
                and time_left > CONFIG["limits"]["retry_min_remaining_seconds"]):
            msg, request_id = call_model(client, opts, lower, system, user)
            usages.append(msg.usage)
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            retried_from, effort = effort, lower
            opts = {**opts, "max_tokens": budgets(opts, lower)[0]}

        disarm_deadline()
        produced = bool(text)  # before any placeholder text replaces it
        if msg.stop_reason == "refusal":
            cat = getattr(getattr(msg, "stop_details", None), "category", None)
            text = f"The model declined to review this diff (category: {cat or 'unspecified'}). Try a different `model=`."
        elif msg.stop_reason == "max_tokens":
            advice = (f"Output hit `max_tokens={opts['max_tokens']}` (thinking counts toward it). "
                      "Re-run with a higher `max_tokens=` or a lower `effort=`.")
            if not produced:
                note = ("> **No review was written: thinking used the entire output budget.** "
                        f"{advice} The cost below was still incurred.")
            else:
                note = f"> **{advice}**"
            text = f"{text}\n\n{note}".strip()
        elif not text:
            text = "The model returned no text. Re-run, or try a different `model=`."

        usd = estimate_cost(opts["prices"], usages)
        cost = f" · ~${usd:.3f}" if usd is not None else ""
        tokens_in, tokens_out = sum(u.input_tokens for u in usages), sum(u.output_tokens for u in usages)
        scan_note = "" if opts["scan"] else "**scan off** (not checked for credentials) · "
        footer = (f"\n\n---\n<sub>`{opts['model_id']}` · effort `{effort}` · focus `{opts['focus']}` · {scan_note}"
                  f"{tokens_in:,} in / {tokens_out:,} out{cost} · "
                  f"stop `{msg.stop_reason}` · `{request_id}` · re-run with `/review` for a fresh review; this one is then collapsed</sub>")
        warning = f"> :warning: **{incomplete}**\n\n" if incomplete else ""
        retry_note = ""
        if retried_from:
            if msg.stop_reason == "end_turn" and produced:
                retry_note = (f"> :information_source: Effort `{retried_from}` used its entire output budget before "
                              f"writing anything; this review is from an automatic retry at `{effort}`.\n\n")
            else:
                if msg.stop_reason == "refusal":
                    outcome = "was declined by the model"
                else:
                    outcome = "was cut off partway" if produced else "did not produce a review either"
                retry_note = (f"> :information_source: Effort `{retried_from}` used its entire output budget, and the "
                              f"automatic retry at `{effort}` {outcome}.\n\n")
        review = warning + retry_note + text + footer
        print(review)
        if post:
            post_review_comment(repo, pr, marker, review, also_collapse=(SCAN_MARKER,))
            react(repo, comment_id, "rocket")
        return 0

    except ReviewTimeout:
        spent = estimate_cost(opts["prices"], usages)
        err = (f"The review timed out after {CONFIG['limits']['deadline_seconds'] // 60} minutes. Tokens the "
               "in-flight request had generated are still billed"
               + (f", on top of ~${spent:.3f} for the attempt(s) that completed" if usages and spent is not None else "")
               + ". Re-run with a lower `effort=` or a smaller `max_tokens=`.")
    except anthropic.RateLimitError:
        err = "Anthropic rate limit hit. Try again in a minute."
    except anthropic.AuthenticationError:
        err = "Anthropic authentication failed. Check the `ANTHROPIC_API_KEY` repo secret."
    except anthropic.BadRequestError as e:
        err = f"Anthropic rejected the request: {e.message[:400]}"
    except anthropic.APIStatusError as e:
        err = f"Anthropic API error ({e.status_code}). Try again."
    except anthropic.APIConnectionError:
        err = "Could not reach the Anthropic API."
    except Exception as e:  # noqa: BLE001 - surface anything else without leaking env
        err = f"Review failed: {type(e).__name__}: {str(e)[:300]}"
    disarm_deadline()
    print(err, file=sys.stderr)
    if post:
        try:  # reporting the failure must never mask it
            post_review_comment(repo, pr, marker, f"Review failed: {err}", collapse_previous=False)
            react(repo, comment_id, "confused")
        except Exception as e:  # noqa: BLE001
            print(f"Could not post the failure comment: {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr")
    ap.add_argument("--repo")
    ap.add_argument("--comment", help="comment text (default: $COMMENT_BODY)")
    ap.add_argument("--no-post", action="store_true", help="print the review instead of commenting")
    ap.add_argument("--dry-run", action="store_true", help="build the request but do not call the API")
    sys.exit(run_review(ap.parse_args()))
