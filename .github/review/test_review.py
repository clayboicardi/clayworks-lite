"""Offline tests for review.py (mocked `gh` and Anthropic client; no network, no key).

Run:  pip install -r .github/review/requirements.txt
      python -m unittest discover -s .github/review -p "test_*.py"
CI:   .github/workflows/review-tests.yml runs this on PRs that touch .github/review/.
"""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review as r  # noqa: E402

DIFF = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,3 +1,4 @@\n one\n-two\n+TWO\n+two-b\n three\n"
LOCK = "diff --git a/package-lock.json b/package-lock.json\n--- a/package-lock.json\n+++ b/package-lock.json\n@@ -1 +1 @@\n-x\n+y\n"
MARKER = "<!-- claude-review:haiku:general -->"
BOT = {"type": "Bot", "login": "github-actions[bot]"}


class ParseTests(unittest.TestCase):
    def test_defaults_and_flags(self):
        opts, note = r.parse_comment("/review model=sonnet effort=xhigh focus=security max_tokens=40000 check cookies\nand tests")
        self.assertEqual((opts["model_id"], opts["effort"], opts["focus"], opts["max_tokens"]),
                         (r.CONFIG["models"]["sonnet"]["id"], "xhigh", "security", 40000))
        self.assertEqual(note, "check cookies\nand tests")
        self.assertEqual(r.parse_comment("/review")[0]["model_key"], r.CONFIG["defaults"]["model"])

    def test_rejects_bad_input(self):
        for bad in ["/review model=gpt5", "/review effort=ultra", "/review foo=1", "/review max_tokens=10",
                    "/reviewx", "hello", "/review focus=nope"]:
            with self.assertRaises(r.UsageError, msg=bad):
                r.parse_comment(bad)

    def test_model_id_injection_rejected(self):
        for bad in ['/review model=claude-"))or(.user.type=="Bot"))|.id#', "/review model=claude-x;rm", "/review model=claude-"]:
            with self.assertRaises(r.UsageError, msg=bad):
                r.parse_comment(bad)
        self.assertEqual(r.parse_comment("/review model=claude-opus-4-8")[0]["model_id"], "claude-opus-4-8")


class TokenBudgetTests(unittest.TestCase):
    def test_every_model_and_effort_gets_a_valid_budget(self):
        """Each model x effort: hard cap well above a valid pacing budget, both within limits."""
        cap, tb_min = r.CONFIG["limits"]["max_tokens_cap"], r.CONFIG["limits"]["task_budget_min"]
        for model in r.CONFIG["models"]:
            for effort in r.CONFIG["efforts"]:
                opts, _ = r.parse_comment(f"/review model={model} effort={effort}")
                self.assertLessEqual(opts["max_tokens"], cap, (model, effort))
                if not r.CONFIG["models"][model].get("task_budget"):
                    self.assertIsNone(opts["task_budget"], (model, effort))
                    continue
                self.assertTrue(opts["task_budget_ok"], (model, effort))
                self.assertIsNotNone(opts["task_budget"], (model, effort))
                self.assertGreaterEqual(opts["task_budget"], tb_min, (model, effort))
                self.assertGreaterEqual(opts["max_tokens"], 2 * opts["task_budget"], (model, effort))

    def test_budgets_grow_with_effort(self):
        eb = r.CONFIG["effort_budgets"]
        efforts = r.CONFIG["efforts"]
        for lo, hi in zip(efforts, efforts[1:]):
            self.assertLess(eb[lo]["max_tokens"], eb[hi]["max_tokens"])
            self.assertLessEqual(eb[lo]["task_budget"], eb[hi]["task_budget"])

    def test_custom_model_id_gets_no_task_budget(self):
        opts, _ = r.parse_comment("/review model=claude-opus-4-8 effort=high")
        self.assertIsNone(opts["task_budget"])
        self.assertEqual(opts["max_tokens"], r.CONFIG["limits"]["custom_model_max_tokens"])
        explicit, _ = r.parse_comment("/review model=claude-opus-4-8 max_tokens=100000")
        self.assertEqual(explicit["max_tokens"], 100000)  # an explicit value still wins

    def test_lower_effort(self):
        self.assertEqual(r.lower_effort("max"), "xhigh")
        self.assertEqual(r.lower_effort("medium"), "low")
        self.assertIsNone(r.lower_effort("low"))

    def test_explicit_max_tokens_wins_and_is_capped(self):
        small, _ = r.parse_comment("/review effort=max max_tokens=5000")
        self.assertEqual((small["max_tokens"], small["task_budget"]), (5000, None))  # too small for a 20k budget
        old_default, _ = r.parse_comment("/review effort=max max_tokens=32000")  # the config that failed on #68
        self.assertEqual((old_default["max_tokens"], old_default["task_budget"]), (32000, 20000))
        edge = r.CONFIG["limits"]["task_budget_min"] + r.CONFIG["limits"]["task_budget_headroom"]
        self.assertIsNotNone(r.parse_comment(f"/review effort=max max_tokens={edge}")[0]["task_budget"])
        self.assertIsNone(r.parse_comment(f"/review effort=max max_tokens={edge - 1}")[0]["task_budget"])
        cap = r.CONFIG["limits"]["max_tokens_cap"]
        self.assertEqual(r.parse_comment(f"/review max_tokens={cap}")[0]["max_tokens"], cap)
        with self.assertRaises(r.UsageError):
            r.parse_comment(f"/review max_tokens={cap + 1}")


@unittest.skipUnless(hasattr(r.signal, "SIGALRM"), "SIGALRM is not available on this platform")
class DeadlineTests(unittest.TestCase):
    def test_alarm_actually_interrupts_a_stuck_call(self):
        import time as real_time
        r.arm_deadline(1)
        try:
            with self.assertRaises(r.ReviewTimeout):
                real_time.sleep(3)
        finally:
            r.disarm_deadline()


def fake_secret(kind):
    # assembled at runtime so this test file's own diff never contains a full credential
    return {
        "anthropic": "sk-" + "ant-api03-" + "A1b2C3d4" * 4,
        "github": "gh" + "p_" + "a1B2c3D4e5" * 4,
        "aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "pem": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "assign": "api_" + 'key = "' + "Zx9Yw8Vu7Ts6Rq5Po4Nm3" + '"',
        "slack": "xo" + "xb-" + "1234567890-" + "abcdefABCDEF",
        "google": "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
        "stripe": "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc",
        "openai": "sk-" + "proj-" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx2",
        "prefixed": "ANTHROPIC_" + "API_KEY = " + '"' + "Zx9Yw8Vu7Ts6Rq5Po4Nm3" + '"',
        "env": "STRIPE_" + "SECRET=" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Zx9",
        "slack_app": "xa" + "pp-1-A0123456789-" + "1234567890123-abcdef0123456789",
        "slack_rotating": "xo" + "xe.xoxp-1-" + "Mi0xLTEyMzQ1Njc4OTAtYWJj",
        "slack_app_env": "SLACK_APP_" + "TOKEN=" + "xa" + "pp-1-A0123456789-1234567890123-abcdef",
        "aws_secret_quoted": "AWS_" + "SECRET_ACCESS_KEY = " + '"' + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzx" + '"',
        "aws_envvar_assign": "AWS_" + "SECRET_ACCESS_KEY=" + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzx",
        "db_password": "DATABASE_" + "PASSWORD = " + '"' + "Zx9Yw8Vu7Ts6Rq5Po4Nm3" + '"',
        "db_password_prod": "database_" + "password_prod: " + '"' + "Zx9Yw8Vu7Ts6Rq5Po4Nm3" + '"',
    }[kind]


def diff_adding(path, *added):
    body = "".join(f"+{line}\n" for line in added)
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,1 +1,{1 + len(added)} @@\n context\n{body}")


class SecretScanTests(unittest.TestCase):
    def test_each_pattern_is_found_with_path_and_line_but_no_value(self):
        for kind, name in [("anthropic", "Anthropic API key"), ("github", "GitHub token"), ("aws", "AWS access key ID"),
                           ("pem", "Private key block"), ("assign", "Hardcoded credential"),
                           ("slack", "Slack token"), ("google", "Google API key"), ("stripe", "Stripe live key"),
                           ("openai", "OpenAI API key"), ("prefixed", "Hardcoded credential"),
                           ("env", "Env-style credential"),
                           ("slack_app", "Slack token"), ("slack_rotating", "Slack token"),
                           ("slack_app_env", "Slack token"),
                           ("aws_secret_quoted", "Hardcoded credential"), ("aws_envvar_assign", "Env-style credential"),
                           ("db_password", "Hardcoded credential"), ("db_password_prod", "Hardcoded credential")]:
            findings = r.scan_for_secrets(diff_adding("src/app.py", "x = 1", fake_secret(kind)))
            self.assertEqual(findings, [("src/app.py", 3, name)], kind)  # context line is L1, so the 2nd added line is L3
            self.assertNotIn(fake_secret(kind), r.secret_notice(findings), kind)

    def test_removed_and_context_lines_are_scanned_because_they_are_sent(self):
        # a PR that deletes a hardcoded key still transmits it in the diff body
        secret = fake_secret("anthropic")
        diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,2 @@\n"
                f" {secret}\n-{fake_secret('github')}\n+fine\n")
        self.assertEqual(r.scan_for_secrets(diff), [
            ("a.py", 1, "Anthropic API key"),                 # unchanged context line, with its new-file line number
            ("a.py (removed line)", None, "GitHub token"),    # removed line: no new-file line number
        ])
        notice = r.secret_notice(r.scan_for_secrets(diff))
        self.assertIn("removed and unchanged context lines are all sent", notice)

    def test_line_numbers_survive_removed_lines_and_multiple_hunks(self):
        diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                "@@ -1,3 +1,3 @@\n a\n-b\n" + "+" + fake_secret("aws") + "\n"
                "@@ -10,2 +10,3 @@\n ten\n+eleven\n+" + fake_secret("slack") + "\n")
        self.assertEqual([(w, ln) for w, ln, _ in r.scan_for_secrets(diff)], [("a.py", 2), ("a.py", 12)])

    def test_unicode_line_separators_do_not_hide_or_shift_anything(self):
        for sep in ("\u2028", "\x0b", "\x0c", "\x85"):
            findings = r.scan_for_secrets(diff_adding("a.py", "harmless" + sep + "still the same line", fake_secret("github")))
            self.assertEqual(findings, [("a.py", 3, "GitHub token")], repr(sep))  # not shifted by the fake break
        # a credential right after a separator is still on the added line, so it is still scanned
        findings = r.scan_for_secrets(diff_adding("a.py", "note\u2028" + fake_secret("aws")))
        self.assertEqual(findings, [("a.py", 2, "AWS access key ID")])

    def test_excluded_files_are_not_scanned_because_they_are_never_sent(self):
        self.assertEqual(r.scan_for_secrets(diff_adding("package-lock.json", fake_secret("anthropic"))), [])

    def test_pr_title_description_and_branch_names_are_scanned(self):
        texts = [("PR title", "rotate " + fake_secret("github")), ("PR description", fake_secret("aws")),
                 ("branch names", "fix/" + fake_secret("github") + " main")]
        findings = r.scan_for_secrets(DIFF, texts)
        self.assertEqual([(w, ln) for w, ln, _ in findings],
                         [("PR title", None), ("PR description", None), ("branch names", None)])

    def test_env_block_pasted_into_a_multiline_description_is_caught(self):
        body = "Setup notes\n\n```\nNODE_ENV=production\n" + fake_secret("env") + "\n```\nthanks"
        findings = r.scan_for_secrets(DIFF, [("PR description", body)])
        self.assertEqual(findings, [("PR description", None, "Env-style credential")])
        findings = r.scan_for_secrets(DIFF, [("PR title", "first line\n" + fake_secret("slack_app_env"))])
        self.assertEqual(findings, [("PR title", None, "Slack token")])

    def test_vendor_tokens_glued_after_an_underscore_are_caught(self):
        for kind, name in [("github", "GitHub token"), ("aws", "AWS access key ID"), ("slack", "Slack token")]:
            findings = r.scan_for_secrets(diff_adding("a.py", "MY_" + fake_secret(kind)))
            self.assertEqual(findings, [("a.py", 2, name)], kind)

    def test_env_line_with_trailing_comment_or_semicolon_is_caught(self):
        value = fake_secret("env")  # STRIPE_SECRET=<value>
        for suffix in ("  # prod", ";", " ; export", "\t# x"):
            findings = r.scan_for_secrets(diff_adding(".env", value + suffix))
            self.assertEqual(findings, [(".env", 2, "Env-style credential")], repr(suffix))

    def test_key_material_without_a_pem_header_is_caught_only_in_key_files(self):
        line = "A1b2C3d4" * 8  # a 64-character base64 line, as in a PEM body
        self.assertEqual(r.scan_for_secrets(diff_adding("deploy/server.pem", line)),
                         [("deploy/server.pem", 2, "Key material in a key file")])
        self.assertEqual(r.scan_for_secrets(diff_adding("home/id_ed25519", line))[0][2], "Key material in a key file")
        self.assertEqual(r.scan_for_secrets(diff_adding("src/app.py", line)), [])  # same text elsewhere is not flagged

    def test_the_review_comment_note_is_scanned_too(self):
        rc, calls, kw = run_with_fakes("/review model=haiku see " + fake_secret("github"), changed_files=1)
        self.assertEqual((rc, kw), (1, []))
        self.assertIn("review comment note", last_write(calls)[0])
        self.assertNotIn(fake_secret("github"), last_write(calls)[0])

    def test_hostile_long_lines_are_scanned_in_linear_time_and_a_hidden_key_is_still_found(self):
        import time as real_time
        n = 100_000  # the 400,000-char diff cap applies before scanning; a quadratic regex takes ~40s even at this size
        hostile = ["token_" * (n // 6), "secret" + " " * n, ("a=" + " ") * (n // 3), "api_key=" + "x" * n,
                   "'" + "password" * (n // 8), "A" * n,
                   # block scalars, Dockerfile ENV, annotations, string prefixes and open triple quotes
                   "A_KEY: |\n" * (n // 8), "ENV A_KEY " * (n // 8), "A_KEY: " + "a | " * n, "A_KEY: " * (n // 4),
                   'A_KEY = """' + "a" * n, "A_KEY = " + "rb" * n, "api_key: str = " + "r" * n]
        for text in hostile:
            for code in (False, True):
                start = real_time.perf_counter()
                r.secret_name(text, code)
                self.assertLess(real_time.perf_counter() - start, 2.0, text[:12])
        # a credential at the far end of a long line is still found
        for pad in (10_000, 2_990, 3_500, 70_000):
            line = "x" * pad + " " + fake_secret("github") + " " + "y" * 50
            self.assertEqual(r.secret_name(line), "GitHub token", pad)
        line = "x" * 50_000 + " " + fake_secret("aws_secret_quoted")
        self.assertEqual(r.secret_name(line), "Hardcoded credential")

    def test_long_multiline_constructs_are_scanned_in_linear_time(self):
        import time as real_time
        # 20,000 backslash-continued lines took 37s while the whole continued line was carried and rescanned on every line
        for path, lines in [("Dockerfile", ["ENV A_KEY \\"] * 10_000), ("c.yml", ["A_KEY: |"] + ["  v1"] * 10_000),
                            ("c.py", ['A_KEY = """'] + ["abc"] * 10_000), ("c.py", ["A_KEY = f(" * 5_000])]:
            start = real_time.perf_counter()
            r.scan_for_secrets(diff_adding(path, *lines))
            self.assertLess(real_time.perf_counter() - start, 20.0, path)

    def test_a_credential_in_an_omitted_file_name_blocks_the_review(self):
        # the prompt lists omitted files by name, so their names are sent even though their content is not
        diff = diff_adding("assets/" + fake_secret("github") + ".png", "binary-ish")
        rc, calls, kw = run_with_fakes("/review model=haiku", changed_files=1, diff=diff)
        body = last_write(calls)[0]
        self.assertEqual((rc, kw), (1, []))
        self.assertIn(r.PATH_LABEL, body)
        self.assertNotIn(fake_secret("github"), body)

    def test_a_bare_carriage_return_does_not_hide_a_credential(self):
        tok = fake_secret("github")
        # CR stays inside the line (gh output is decoded from bytes, with no newline translation)
        self.assertEqual(r.scan_for_secrets(diff_adding("a.py", "x\r" + tok)), [("a.py", 2, "GitHub token")])
        # and even if a fragment ever arrives without its diff prefix, its first character is kept
        diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,2 @@\n ctx\n+x\n" + tok + "\n"
        self.assertEqual([n for _, _, n in r.scan_for_secrets(diff)], ["GitHub token"])

    def test_gh_output_is_decoded_without_newline_translation(self):
        out = ("+x\rghp_" + "a" * 36 + "\n").encode("utf-8")
        done = types.SimpleNamespace(returncode=0, stdout=out, stderr=b"")
        with mock.patch.object(r.subprocess, "run", return_value=done) as run:
            text = r.gh("pr", "diff", "1")
        self.assertIn("\r", text)  # a bare CR is preserved, so the line is not split into an unprefixed fragment
        self.assertNotIn("text", run.call_args.kwargs)

    def test_env_style_credentials_inside_path_or_ref_components_are_caught(self):
        env = fake_secret("aws_envvar_assign")  # AWS_SECRET_ACCESS_KEY=<value>
        # an omitted file whose name holds the credential below a directory (the prompt lists omitted names)
        diff = diff_adding("assets/" + env + "/image.png", "binary-ish")
        rc, calls, kw = run_with_fakes("/review model=haiku", changed_files=1, diff=diff)
        self.assertEqual((rc, kw), (1, []))
        self.assertNotIn(env, last_write(calls)[0])
        # a non-excluded path: the path is in every header line that is sent
        findings = r.scan_for_secrets(diff_adding("src/" + env + "/app.py", "x = 1"))
        self.assertEqual(findings, [(r.PATH_LABEL, None, "Env-style credential")])
        # a branch name below a prefix
        rc, calls, kw = run_with_fakes("/review model=haiku", changed_files=1, head_ref="feature/" + env)
        self.assertEqual((rc, kw), (1, []))

    def test_punctuated_passwords_in_config_and_env_files_are_caught(self):
        pw = "A1!correct-horse-" + "battery-staple"  # any punctuation: a literal value in a config file
        for path, line in [(".env", "DATABASE_" + "PASSWORD=" + pw), ("docker-compose.yml", "      - DATABASE_" + "PASSWORD=" + pw),
                           ("Dockerfile", "ENV DATABASE_" + "PASSWORD=" + pw), ("deploy.sh", "export DB_" + "SECRET=" + pw),
                           ("settings.ini", "API_" + "KEY=Zx9!Yw8@Vu7$Ts6")]:
            findings = r.scan_for_secrets(diff_adding(path, line))
            self.assertEqual([(w, n) for w, _, n in findings], [(path, "Env-style credential")], path)
            self.assertNotIn(pw, r.secret_notice(findings))
        # the same literal in a PR description or branch name (no file type) counts too
        self.assertEqual(r.secret_name("DATABASE_" + "PASSWORD=" + pw), "Env-style credential")

    def test_quoted_punctuated_values_are_literals_in_every_file_type(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [(".env", "DATABASE_" + 'PASSWORD="' + pw + '"'), ("deploy.sh", "export DB_" + "SECRET='" + pw + "'"),
                           ("config.py", "DATABASE_" + 'PASSWORD = "' + pw + '"'),
                           ("app.js", "const API_" + "KEY = '" + pw + "';"),
                           ("compose.yml", "      DATABASE_" + 'PASSWORD: "x" # DB_' + 'PASSWORD="' + pw + '"')]:
            findings = r.scan_for_secrets(diff_adding(path, line))
            self.assertEqual([(w, n) for w, _, n in findings], [(path, "Env-style credential")], path)
            self.assertNotIn(pw, r.secret_notice(findings))

    def test_quoted_placeholders_references_and_prose_are_not_flagged(self):
        for line in ('API_' + 'KEY="${API_KEY}"', 'API_' + 'KEY="<your-key-goes-here-1>"', 'API_' + 'KEY="YOUR_API_KEY_HERE_V2"',
                     'API_' + 'KEY="Enter your API key here"', 'API_' + 'KEY=""', "API_" + "KEY='short'"):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)
            self.assertEqual(r.scan_for_secrets(diff_adding("config.js", line)), [], line)

    def test_a_name_and_value_split_over_lines_in_pr_text_is_caught(self):
        value = "Zx9Yw8Vu7Ts6Rq5Po4Nm3"
        for body in ('Notes\n"api_' + 'key":\n  "' + value + '"\nthanks', "DATABASE_" + "PASSWORD=\nZx9Yw8Vu7Ts6Rq5Po4Nm3Zx9\n",
                     "intro\nexport STRIPE_" + "SECRET=\n  " + value + "Zx9"):
            findings = r.scan_for_secrets(DIFF, [("PR description", body)])
            self.assertEqual([w for w, _, _ in findings], ["PR description"], body)
        # ordinary two-line text is not flagged
        self.assertEqual(r.scan_for_secrets(DIFF, [("PR description", "The token:\nis described in the docs below")]), [])
        # the /review note is scanned the same way, and each text is isolated from the next (no join across texts)
        findings = r.scan_for_secrets(DIFF, [("PR title", "DATABASE_" + "PASSWORD="), ("PR description", "A1!correct-horse-battery-staple")])
        self.assertEqual(findings, [])

    def test_source_files_keep_the_strict_unquoted_rule(self):
        pw = "DATABASE_" + "PASSWORD=A1!correct-horse-battery-staple"
        self.assertEqual(r.scan_for_secrets(diff_adding("config.py", pw)), [])  # an expression-like RHS in code
        token = fake_secret("env")  # NAME_SECRET=<digit-bearing alphanumerics>
        self.assertEqual([n for _, _, n in r.scan_for_secrets(diff_adding("config.py", token))], ["Env-style credential"])
        # references and placeholders are not credentials in any file type
        for line in ("API_" + "KEY=${API_KEY}", "API_" + "KEY=<your-api-key-goes-here>",
                     "API_" + "KEY=changeme_please_change_me"):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)

    def test_placeholder_only_means_every_word_is_a_placeholder_word(self):
        for placeholder in ("your_api_key_here", "YOUR-API-KEY-HERE-V2", "changeme_please_change_me", "CHANGEME",
                            "xxxxxxxxxxxxxxxx", "replace_with_your_key_123456", "put_your_secret_here"):
            self.assertTrue(r.placeholder_only(placeholder), placeholder)
        for numeric in ("12345678901234567890", "1234-5678-9012-3456", "v2", "000000000000", "42"):
            self.assertFalse(r.placeholder_only(numeric), numeric)  # a PIN or numeric key is not a placeholder
        for secret in ("correct_horse_here_staple", "example_correct_horse", "Zx9Yw8Vu7Ts6Rq5Po4Nm3Zx9",
                       "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzx", "correct_horse_battery_staple", "A1!correct-horse-battery"):
            self.assertFalse(r.placeholder_only(secret), secret)  # a passphrase containing a placeholder word is real

    def test_fallbacks_inside_references_are_scanned_not_exempted(self):
        tok = "Zx9Yw8Vu7Ts6Rq5Po4Nm3Zx9"
        for line in ('API_' + 'KEY="${API_KEY:-' + tok + '}"', 'API_' + 'KEY="${PREFIX}-' + tok + '"',
                     'API_' + 'KEY="${A:-${B:-' + tok + '}}"'):
            for path in (".env", "app.js"):  # quoted values are literals in every file type
                self.assertEqual([n for _, _, n in r.scan_for_secrets(diff_adding(path, line))], ["Env-style credential"],
                                 (path, line))
        unquoted = "API_" + "KEY=${API_KEY:-" + tok + "}"  # an unquoted expansion with a literal fallback (config/env files)
        self.assertEqual([n for _, _, n in r.scan_for_secrets(diff_adding(".env", unquoted))], ["Env-style credential"])
        self.assertTrue(r.is_reference("${A}-${B}", '"'))
        self.assertTrue(r.is_reference("${A:-changeme}", '"'))
        self.assertFalse(r.is_reference("${A:-" + tok + "}", '"'))
        self.assertFalse(r.is_reference("${A}x9Yw8Vu7Ts6Rq5", '"'))  # literal text after a reference

    def test_credential_bearing_urls_and_slashy_secrets_are_not_exempt(self):
        tok = "Zx9Yw8Vu7Ts6Rq5Po4Nm3"
        for value in ("https://prod.internal/cb?api_" + "key=" + tok, "https://prod.internal/" + tok + "/callback.json",
                      "https://x.org/a?token=abcdefghijklmnopqrstuvwxyz", "/srv/keys/" + tok + ".pem",
                      "https://prod.internal/aB3dE5fG7h/iJ9kL1mN3o/cb.json"):
            line = "API_" + 'KEY="' + value + '"'
            self.assertTrue(r.scan_for_secrets(diff_adding("app.js", line)), value)  # flagged by one rule or the other
        for value in ("https://example.com/keys/current.pem", "keys/public/current.pem", "../keys/public/current.pem"):
            self.assertEqual(r.scan_for_secrets(diff_adding("app.js", "PUBLIC_" + 'KEY="' + value + '"')), [], value)
        # an AWS-style secret contains slashes but has no extension, so it is not a path
        self.assertFalse(r.non_secret_literal("wJalrXUtnFEMI/K7MDENG/bPxRfiCYzx"))

    def test_uppercase_passphrases_in_quotes_are_literals_but_unquoted_constants_are_not(self):
        quoted = "DATABASE_" + 'PASSWORD="CORRECT_HORSE_' + 'BATTERY_STAPLE"'  # assembled: this file is self-scanned
        for path in ("config.py", ".env"):
            self.assertTrue(r.scan_for_secrets(diff_adding(path, quoted)), path)  # a string literal, whatever its spelling
        self.assertEqual(r.scan_for_secrets(diff_adding("app.js", "const API_" + "KEY = REACT_APP_API_KEY_V2_PRODUCTION;")), [])
        # in a dotenv/shell/YAML file a bare right-hand side is a literal value, not a reference to anything
        for path, line in [(".env", "DATABASE_" + "PASSWORD=CORRECT_HORSE_" + "BATTERY_STAPLE"),
                           ("deploy.sh", "export DB_" + "SECRET=CORRECT_HORSE_" + "BATTERY_STAPLE"),
                           ("config.yml", "DATABASE_" + "PASSWORD: CORRECT_HORSE_" + "BATTERY_STAPLE")]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))

    def test_multiply_namespaced_url_parameters_and_hosts(self):
        for param in ("oauth_client_secret", "x-oauth-client-secret", "my.app.api_key", "a_b_c_refresh_token"):
            self.assertFalse(r.non_secret_literal("https://auth.internal/cb?" + param + "=abcdefghijklmnopqrstuvwxyz"), param)
        # a long hostname with letters and digits is a name, not a token; a query on a bare host is still inspected
        self.assertTrue(r.non_secret_literal("https://productioncluster2026.example.com/keys/current.pem"))
        self.assertFalse(r.non_secret_literal("https://x.org?token=abcdefghijklmnopqrstuvwxyz"))
        self.assertFalse(r.non_secret_literal("https://x.org?ref=aB3dE5fG7hiJ9kL1mN3o"))  # token-shaped query on a bare host
        self.assertFalse(r.non_secret_literal("https://x.org/aB3dE5fG7h/iJ9kL1mN3o/cb.json"))

    def test_a_metadata_word_followed_by_a_credential_keyword_is_a_credential(self):
        pw = "Zx9Yw8Vu7Ts6Rq5Po4" + "Nm3Zx9"
        for line in ("API_" + "KEY_PROVIDER_TOKEN=" + pw, "SECRET_" + "KEY_FILE_PASSWORD=" + pw):
            self.assertTrue(r.scan_for_secrets(diff_adding(".env", line)), line)
        for line in ("API_" + "KEY_FILE=" + pw, "TOKEN_" + "EXPIRY_POLICY=" + pw):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)  # descriptive: the setting is about a key
        self.assertTrue(r.metadata_name("KEY_FILE") and not r.metadata_name("KEY_PROVIDER_TOKEN"))
        # the quoted-assignment rule reads the name the same way
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", "api_key_provider_" + 'token = "' + pw + pw + '"')))

    def test_type_annotations_before_the_value(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [("config.py", "API_" + 'KEY: str = "' + pw + '"'), ("config.py", "DB_" + "PASSWORD: Final[str] = '" + pw + "'"),
                           ("config.py", "DB_" + "PASSWORD: str | None = '" + pw + "'"),
                           ("config.ts", "const API_" + "KEY: string = '" + pw + "';"),
                           ("config.py", "api_" + 'key: str = "correct_horse_' + 'battery_staple"')]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        for path, line in [("types.ts", "API_" + "KEY: string;"), ("config.py", "API_" + "KEY: str = os.environ.get_value"),
                           ("config.py", "API_" + "KEY: str = REACT_APP_API_KEY_V2")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_yaml_block_scalars(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for marker in ("|", ">", "|-", ">+", "|2"):
            findings = r.scan_for_secrets(diff_adding("config.yml", "DATABASE_" + "PASSWORD: " + marker, "  " + pw))
            self.assertEqual([(w, n) for w, _, n in findings], [("config.yml", "Env-style credential")], marker)
        # a block scalar holding ordinary prose, or a marker with nothing after it, is not a credential
        self.assertEqual(r.scan_for_secrets(diff_adding("config.yml", "DATABASE_" + "PASSWORD: |", "  see the vault for the real value")), [])
        self.assertEqual(r.scan_for_secrets(diff_adding("config.yml", "DATABASE_" + "PASSWORD: |")), [])

    def test_dockerfile_space_separated_env(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for line in ("ENV DATABASE_" + "PASSWORD " + pw, "ENV DATABASE_" + 'PASSWORD "' + pw + '"', "ENV DB_" + "SECRET_PROD\t" + pw):
            findings = r.scan_for_secrets(diff_adding("Dockerfile", line))
            self.assertEqual([n for _, _, n in findings], ["Env-style credential"], line)
        for line in ("ENV NODE_ENV production", "ENV PORT 8080", "ENV API_" + "KEY ${API_KEY}", "ENV TOKEN_" + "EXPIRY_POLICY slidingexpiration"):
            self.assertEqual(r.scan_for_secrets(diff_adding("Dockerfile", line)), [], line)

    def test_python_string_prefixes_triple_quotes_and_backticks(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [("c.py", "DATABASE_" + 'PASSWORD = r"A1!correct\\horse-' + 'battery-staple"'),
                           ("c.py", "DATABASE_" + "PASSWORD = b'" + pw + "'"), ("c.py", "DATABASE_" + 'PASSWORD = f"' + pw + '"'),
                           ("c.py", "DATABASE_" + 'PASSWORD = """' + pw + '"""'), ("c.py", "DATABASE_" + "PASSWORD = '''" + pw + "'''"),
                           ("c.js", "const DATABASE_" + "PASSWORD = `" + pw + "`;"),
                           ("c.py", "api_" + 'key = rb"correct_horse_' + 'battery_staple"')]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        for path, line in [("c.py", "API_" + 'KEY = r"${API_KEY}"'), ("c.py", "API_" + 'KEY = """"""'),
                           ("c.js", "const API_" + "KEY = `${API_KEY}`;")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_member_paths_are_references_only_in_expression_files(self):
        for path in ("main.tf", "vars.hcl", "app.js", "config.py"):
            for line in ("API_" + "KEY = local.application_api_key", "DB_" + "PASSWORD = config.database.password_value"):
                self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))
        # in a dotenv, YAML, INI or shell file the right-hand side is a literal, whatever it looks like
        for path, line in [(".env", "DATABASE_" + "PASSWORD=correct.horse.battery.staple"),
                           ("settings.ini", "DATABASE_" + "PASSWORD=correct.horse.battery.staple"),
                           ("config.yml", "DATABASE_" + "PASSWORD: correct.horse.battery.staple"),
                           ("deploy.sh", "export DB_" + "SECRET=correct.horse.battery.staple")]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))

    def test_block_scalars_are_followed_past_the_first_line(self):
        pw = "A1!correct-horse-" + "battery-staple"
        diff = diff_adding("config.yml", "DATABASE_" + "PASSWORD: |", "  version1", "  " + pw)
        self.assertEqual([(w, n) for w, _, n in r.scan_for_secrets(diff)], [("config.yml", "Env-style credential")])
        # a blank line inside the scalar does not end it
        diff = diff_adding("config.yml", "DATABASE_" + "PASSWORD: |", "  version1", "", "  " + pw)
        self.assertEqual(len(r.scan_for_secrets(diff)), 1)
        # a less-indented line ends it; what follows is an ordinary mapping
        diff = diff_adding("config.yml", "DATABASE_" + "PASSWORD: |", "  version1", "other: value", "  " + pw)
        self.assertEqual(r.scan_for_secrets(diff), [])

    def test_multiline_triple_quoted_credentials(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for opener in ('"""', "'''"):
            diff = diff_adding("config.py", "DATABASE_" + "PASSWORD = " + opener, pw, opener)
            self.assertEqual([(w, n) for w, _, n in r.scan_for_secrets(diff)], [("config.py", "Env-style credential")], opener)
        diff = diff_adding("config.py", "DATABASE_" + 'PASSWORD: str = r"""', "    " + pw, '"""')
        self.assertTrue(r.scan_for_secrets(diff))
        # a placeholder inside, and anything after the closing delimiter, are not credentials
        self.assertEqual(r.scan_for_secrets(diff_adding("config.py", "API_" + 'KEY = """', "your_api_key_here", '"""')), [])
        self.assertEqual(r.scan_for_secrets(diff_adding("config.py", "API_" + 'KEY = """', "x", '"""', pw)), [])

    def test_backslash_continued_values(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, lines in [("Dockerfile", ("ENV DATABASE_" + "PASSWORD \\", pw)),
                            ("Dockerfile", ("ENV DATABASE_" + "PASSWORD=\\", pw)),
                            ("deploy.sh", ("export DB_" + "SECRET=\\", "  " + pw)),
                            ("Dockerfile", ("ENV A=1 \\", "    DB_" + "PASSWORD=\\", "    " + pw))]:
            findings = r.scan_for_secrets(diff_adding(path, *lines))
            self.assertEqual([n for _, _, n in findings], ["Env-style credential"], lines)
        for lines in [("ENV PORT 8080 \\", "    NODE_ENV=production"), ("RUN apt-get update && \\", "    apt-get install -y curl")]:
            self.assertEqual(r.scan_for_secrets(diff_adding("Dockerfile", *lines)), [], lines)

    def test_metadata_named_settings_still_have_their_value_checked(self):
        sample = "abcdefghijklmnopqrstuvwxyz"
        for line in ("API_" + 'KEY_URL="https://auth.example/cb?client_secret=' + sample + '"',
                     "TOKEN_" + "ENDPOINT=https://svc:" + "Zx9Yw8Vu7Ts6@auth.example/token",
                     "API_" + "KEY_FILE=https://auth.example/cb?api_key=" + sample):
            self.assertTrue(r.scan_for_secrets(diff_adding(".env", line)), line)
        for line in ("API_" + 'KEY_URL="https://auth.example/cb?client_secret=${CLIENT_SECRET}"', "API_" + "KEY_FILE=/etc/keys/api.key",
                     "TOKEN_" + "ENDPOINT=https://oauth.example/token", "API_" + "KEY_URL=https://auth.example/cb?token=your_token_here",
                     "TOKEN_" + "ENDPOINT=https://svc:${PASSWORD}@auth.example/token"):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)

    def test_literals_nested_in_source_expressions(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [("c.py", "API_" + 'KEY: str = os.getenv("API_KEY", "' + pw + '")'),
                           ("c.py", "API_" + 'KEY = settings.API_KEY or "' + pw + '"'),
                           ("c.js", "const API_" + "KEY = process.env.API_KEY || '" + pw + "';"),
                           ("c.py", "API_" + 'KEY = os.environ.get("A", default="' + pw + '")'),
                           ("c.py", "API_" + 'KEY = SecretStr("' + pw + '")'),  # a first argument that is clearly not a key name
                           ("c.py", "API_" + 'KEY = Secret("Zx9Yw8Vu7Ts6Rq5Po4' + 'Nm3Zx9")')]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        for path, line in [("c.py", "API_" + 'KEY = os.environ.get("MY_SERVICE_API_KEY")'), ("c.py", "API_" + 'KEY = os.getenv("API_KEY", "")'),
                           ("c.js", "const config = { API_" + "KEY: process.env.X, other: 'some-long-string-with-digit-1' };"),
                           ("c.py", "API_" + 'KEY = headers.get("X-Api-Key-Header-Name")'),
                           ("c.py", "API_" + 'KEY = os.getenv("API_KEY", "your_api_key_here")'),
                           ("c.py", "API_" + 'KEY = os.getenv("API_KEY", "https://api.example.com/v1")'),
                           ("c.py", "API_" + 'KEY = get_secret("projects/my-project-123/secrets/api-key/versions/latest")'),
                           ("c.py", "API_" + 'KEY = re.compile(r"^[A-Za-z0-9_-]{20,}$")'),
                           ("c.py", "TOKEN_" + 'RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")'),
                           ("c.py", "PASSWORD_" + 'FORMAT = "min-12-chars-1-digit"')]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_f_string_references(self):
        for line in ("API_" + 'KEY = f"{settings.API_KEY}"', "API_" + 'KEY = f"{prefix}-{name}"', "API_" + "KEY = rf'{a.b}'"):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)
        # a literal portion of the f-string is still scanned
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", "API_" + 'KEY = f"{prefix}-A1!correct-' + 'horse-battery"')))

    def test_pwd_pass_and_passphrase_names(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [(".env", "DB_" + 'PWD="' + pw + '"'), (".env", "DB_" + "PASS=" + pw), (".env", "GPG_" + "PASSPHRASE=" + pw),
                           ("c.py", "db_" + 'pwd = "correct_horse_' + 'battery_staple"'), ("c.py", "db_" + 'pass = "correct_horse_' + 'battery_staple"')]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        # PASS only counts as a delimited word: not BYPASS / COMPASS
        for path, line in [(".env", "BY" + "PASS=01234567" + "89abcdef0123"), ("c.py", "compass_" + 'heading = "0123456789abcdef0123"'),
                           ("c.py", "bypass" + ' = "0123456789abcdef0123"')]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_metadata_named_settings_wrapping_their_value_in_an_expression(self):
        sample = "abcdefghijklmnopqrstuvwxyz"
        line = "API_" + 'KEY_URL = URL("https://auth.example/cb?client_secret=' + sample + '")'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        for line in ("API_" + 'KEY_URL = URL("https://auth.example/cb")', "API_" + 'KEY_FILE = Path("/etc/keys/api.key")',
                     "API_" + 'KEY_URL = URL("https://auth.example/cb?client_secret=${CLIENT_SECRET}")'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_generic_query_parameters_need_a_token_shaped_value(self):
        for line in ("API_" + "KEY_DOCS_URL=https://docs.example/search?key=overview", "API_" + "KEY_DOCS_URL=https://docs.example/p?auth=login&sig=terms"):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)
        for line in ("API_" + "KEY_URL=https://svc.example/cb?token=Zx9Yw8Vu7Ts6" + "Rq5Po4Nm3",
                     "API_" + "KEY_URL=https://svc.example/cb?client_secret=abcde" + "fghij",
                     "API_" + "KEY_URL=https://svc.example/cb?token=abcdefghijklm" + "nopqrstuvwxyz"):
            self.assertTrue(r.scan_for_secrets(diff_adding(".env", line)), line)

    def test_value_constructors_are_judged_like_quoted_values(self):
        for line in ("DATABASE_" + 'PASSWORD = SecretStr("correct-horse-' + 'battery-staple")', "API_" + 'KEY = pydantic.SecretStr("correct-horse-' + 'battery-staple")',
                     "DATABASE_" + 'PASSWORD = Password("correct-horse-' + 'battery-staple")'):
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)
        # lookups keep their lenient first-argument rule
        for line in ("API_" + 'KEY = get_secret("projects/my-project-123/secrets/api-key/versions/latest")', "API_" + 'KEY = getSecret("prod/db/password-primary")',
                     "DATABASE_" + 'PASSWORD = os.environ["DATABASE_PASSWORD_PRIMARY"]'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_adjacent_and_concatenated_literals_are_one_value(self):
        for line in ("API_" + 'KEY = ("A1!correct-" ' + '"horse-battery-staple")', "API_" + 'KEY = "A1!correct-" ' + '"horse-battery-staple"',
                     "API_" + 'KEY = "A1!correct-"' + ' + "horse-battery-staple"', "API_" + "KEY = os.getenv('K', 'A1!correct-'" + " 'horse-battery-staple')"):
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)
        # fragments that are not one credential
        for line in ("API_" + 'KEY = os.getenv("API_" "KEY")', "API_" + 'KEY = "some " + "words"'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_an_escaped_delimiter_does_not_close_a_triple_quoted_string(self):
        pw = "A1!correct-horse-" + "battery-staple"
        diff = diff_adding("config.py", "DATABASE_" + 'PASSWORD = """', 'not-secret \\"""', pw, '"""')
        self.assertEqual([(w, n) for w, _, n in r.scan_for_secrets(diff)], [("config.py", "Env-style credential")])

    def test_yaml_sequence_entries_and_block_header_modifier_orders(self):
        pw = "A1!correct-horse-" + "battery-staple"
        # `- KEY: |` is indented at the key, so a sibling mapping key ends the scalar
        diff = diff_adding("config.yml", "- DATABASE_" + "PASSWORD: |", "    external", "  description: deployed service")
        self.assertEqual(r.scan_for_secrets(diff), [])
        diff = diff_adding("config.yml", "- DATABASE_" + "PASSWORD: |", "    " + pw)
        self.assertEqual(len(r.scan_for_secrets(diff)), 1)
        for marker in ("|2-", ">2+", "|-2", ">+1", "|2"):
            diff = diff_adding("config.yml", "DATABASE_" + "PASSWORD: " + marker, "  " + pw)
            self.assertEqual(len(r.scan_for_secrets(diff)), 1, marker)

    def test_f_string_references_with_index_and_call_suffixes(self):
        for line in ("API_" + "KEY = f\"{settings['API_KEY']}\"", "API_" + 'KEY = f"{get_api_key()}"', "API_" + 'KEY = f"{cfg.keys[0]}-{name!r}"'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)
        # text outside the braces, or a literal inside them, is still scanned
        for line in ("API_" + 'KEY = f"{get_api_key()}-A1!correct-' + 'horse-battery"', "API_" + "KEY = f\"{'A1!correct-" + "horse-battery'}\""):
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_shell_working_directory_variables_are_not_passwords(self):
        for path, line in [("env.sh", "export PWD=/workspace/my-project"), (".env", "OLDPWD=/home/developer/project")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], line)
        self.assertTrue(r.scan_for_secrets(diff_adding(".env", "DB_" + "PWD=/workspace/my-project-Zx9Yw8Vu7Ts6")))

    def test_continuations_are_tracked_separately_for_the_old_and_new_side(self):
        pw = "A1!correct-horse-" + "battery-staple"
        header = "diff --git a/Dockerfile b/Dockerfile\n--- a/Dockerfile\n+++ b/Dockerfile\n@@ -1,2 +1,2 @@\n"
        # context name line, a removed placeholder, then the added real value: the removed line must not consume the state
        diff = header + " ENV DATABASE_" + "PASSWORD \\\n-    your-password-here\n+    " + pw + "\n"
        self.assertEqual([(w, n) for w, _, n in r.scan_for_secrets(diff)], [("Dockerfile", "Env-style credential")])
        header = "diff --git a/c.env b/c.env\n--- a/c.env\n+++ b/c.env\n@@ -1,2 +1,2 @@\n"
        pw = "Zx9Yw8Vu7Ts6Rq5Po4" + "Nm3Zx9"  # on the line after `NAME=` a value needs no punctuation to be recognised
        diff = header + " DB_" + "PASSWORD=\n-old-value\n+" + pw + "\n"
        self.assertEqual([(w, n) for w, _, n in r.scan_for_secrets(diff)], [("c.env", "Env-style credential")])
        # an added value after a removed secret is still attributed to the added line, not the removed one
        diff = header + " DB_" + "PASSWORD=\n-" + pw + "\n+changeme\n"
        self.assertEqual([w for w, _, _ in r.scan_for_secrets(diff)], ["c.env (removed line)"])

    def test_namespaced_parameter_names_are_classified_whole(self):
        # an explicit name counts on length; only a bare generic name needs a token-shaped value
        for param in ("api_key", "access_token", "refresh_token", "id_token", "x-api-key", "client_secret", "app.password",
                      "secret_key", "private_key", "access_key", "client_key", "x-auth-token"):
            line = "API_" + "KEY_URL=https://svc.example/cb?" + param + "=abcdefghij" + "klmnop"
            self.assertTrue(r.scan_for_secrets(diff_adding(".env", line)), param)
        for param in ("key", "token", "auth", "search_key", "sort_key", "cache_key", "primary_key"):
            line = "API_" + "KEY_URL=https://svc.example/cb?" + param + "=abcdefghij" + "klmnop"
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], param)

    def test_value_constructor_keyword_arguments_are_values(self):
        for line in ("DATABASE_" + 'PASSWORD = Password(value="correct-horse-' + 'battery-staple")',
                     "DATABASE_" + 'PASSWORD = Credentials(user="admin", password="correct-horse-' + 'battery-staple")'):
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)
        for line in ("API_" + 'KEY = lookup(name="my-service-key")', "API_" + 'KEY = Password(os.getenv("API_KEY_PRIMARY"))'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_parenthesised_concatenation_across_lines(self):
        diff = diff_adding("c.py", "API_" + "KEY = (", '    "A1!correct-"', '    "horse-battery-staple"', ")")
        self.assertEqual([(w, ln, n) for w, ln, n in r.scan_for_secrets(diff)], [("c.py", 4, "Env-style credential")])
        diff = diff_adding("c.py", "API_" + "KEY = (", '    "A1!correct-" +', '    "horse-battery-staple"', ")")
        self.assertTrue(r.scan_for_secrets(diff))
        # a lookup in parentheses, and anything after the closing parenthesis, are not credentials
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", "API_" + "KEY = (", '    os.getenv("API_KEY")', ")")), [])
        diff = diff_adding("c.py", "API_" + "KEY = (", '    os.getenv("API_KEY")', ")", '"A1!correct-" "horse-battery-staple"')
        self.assertEqual(r.scan_for_secrets(diff), [])

    def test_f_string_lookup_calls_with_quoted_keys_are_references(self):
        for line in ("API_" + "KEY = f\"{os.getenv('API_KEY')}\"", "API_" + "KEY = f\"{settings.get('API_KEY')}\""):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", "API_" + "KEY = f\"{os.getenv('API_KEY')}-A1!correct-" + 'horse"')))

    def test_pwd_is_exempt_only_with_a_path_value(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [("config.yml", "PWD" + ': "' + pw + '"'), (".env", "PWD" + "=" + pw), ("config.yml", "OLDPWD" + ": " + pw)]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        for path, line in [("env.sh", "export PWD=/workspace/my-project"), (".env", "OLDPWD=/home/developer/project"),
                           ("env.sh", "PWD=$(pwd)"), ("env.bat", "PWD=C:\\Users\\dev\\project")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_lowercase_credential_keys_in_config_files(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [("config.yml", "database_" + "password: " + pw), ("application.properties", "spring.datasource." + "password=" + pw),
                           ("settings.ini", "db_" + "pwd = " + pw), ("config.json", '"api_' + 'key": "' + pw + '"'),
                           ("deploy.sh", "db_" + "password=" + pw), ("config.yml", "sec" + "ret: " + pw),
                           ("config.yml", "client-" + "secret: " + pw)]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        # lowercase YAML block scalars follow the same rule as upper-case ones
        diff = diff_adding("config.yml", "database_" + "password: |", "  version1", "  " + pw)
        self.assertEqual([(w, n) for w, _, n in r.scan_for_secrets(diff)], [("config.yml", "Env-style credential")])
        # references, placeholders, settings about a credential and bare `key` names are not credentials
        for path, line in [("config.yml", "password: ${DB_PASSWORD}"), ("config.yml", "password: changeme-please"),
                           ("config.yml", "sort_key: created_at_descending"), ("config.yml", "password_min_length: 12345678901234"),
                           ("config.yml", "token_endpoint: https://oauth.example/token"), ("config.yml", "token: ${{ secrets.GITHUB_TOKEN }}"),
                           ("config.yml", "secretName: db-credentials-prod"), ("config.yml", "password: postgres"),
                           ("config.yml", "callback: https://svc.example/cb?token=Zx9Yw8Vu7Ts6")]:  # a URL's query is not an assignment
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))
        # in source files a lowercase key assigned an unquoted value is an expression, as before
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", "password = os.environ['DATABASE_PASSWORD_PRIMARY']")), [])

    def test_only_the_lookup_key_of_an_f_string_call_is_exempt(self):
        line = "API_" + "KEY = f\"{os.getenv('API_KEY','amber-violin-" + "cactus-orbit')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        for line in ("API_" + "KEY = f\"{os.getenv('API_KEY',fallback)}\"", "API_" + "KEY = f\"{os.getenv('API_KEY')}\""):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_value_constructor_metadata_keywords_are_not_values(self):
        for line in ("API_" + 'KEY = Credential(name="billing-service-api-key", value=os.getenv("API_KEY"))',
                     "API_" + 'KEY = Credential(username="billing-service-account-01", password=os.getenv("API_KEY"))'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)
        line = "API_" + 'KEY = Credential(username="billing-service-account-01", password="correct-horse-' + 'battery-staple")'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))

    def test_windows_working_directories(self):
        for path, line in [("env.bat", "set PWD=\\\\server\\share\\project"), ("env.bat", "set PWD=%CD%"), ("env.bat", "set PWD=%USERPROFILE%\\project-workspace"),("env.bat", "set OLDPWD=C:\\work")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_references_to_where_a_secret_is_stored_are_not_secrets(self):
        for line in ("secret: arn:aws:secretsmanager:us-east-1:123456789012:secret:prod/database", "password: op://vault/db/password",
                     "token: vault:secret/data/app", "api_key: ref+awssecrets://prod/db",
                     "secret: projects/my-project-123/secrets/api-key/versions/latest"):
            self.assertEqual(r.scan_for_secrets(diff_adding("config.yml", line)), [], line)
        self.assertEqual(r.scan_for_secrets(diff_adding(".env", "DATABASE_" + "PASSWORD=arn:aws:secretsmanager:us-east-1:123456789012:secret:prod")), [])

    def test_multiline_call_expressions_after_a_credential_assignment(self):
        diff = diff_adding("c.py", "API_" + "KEY = os.getenv(", '    "API_KEY",', '    "amber-violin-cactus-orbit-47",', ")")
        self.assertEqual([(w, ln) for w, ln, _ in r.scan_for_secrets(diff)], [("c.py", 4)])
        diff = diff_adding("c.py", "API_" + "KEY: str = os.getenv(", '    "API_KEY",', '    default="amber-violin-cactus-orbit-47",', ")")
        self.assertTrue(r.scan_for_secrets(diff))
        # lookups with a placeholder fallback, and anything after the closing parenthesis, are not credentials
        diff = diff_adding("c.py", "API_" + "KEY = os.getenv(", '    "API_KEY",', '    "changeme-please",', ")")
        self.assertEqual(r.scan_for_secrets(diff), [])
        diff = diff_adding("c.py", "API_" + "KEY = os.getenv(", '    "API_KEY",', ")", 'x = "amber-violin-cactus-orbit-47"')
        self.assertEqual(r.scan_for_secrets(diff), [])

    def test_a_value_constructor_inside_an_f_string_is_not_a_lookup(self):
        line = "API_" + "KEY = f\"{ApiKey('A1correct-horse-" + "battery-staple')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        for line in ("API_" + "KEY = f\"{os.getenv('API_KEY')}\"", "API_" + "KEY = f\"{ApiKey(secret_name)}\""):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_metadata_keyword_arguments_are_still_checked_for_embedded_credentials(self):
        line = "API_" + 'KEY = Credential(url="https://user:Zx9Yw8' + 'Vu7Ts6@host")'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        for line in ("API_" + 'KEY = Credential(url="https://auth.example/cb", password=os.getenv("API_KEY"))',
                     "API_" + 'KEY = Credential(name="billing-service-api-key", value=os.getenv("API_KEY"))'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_pwd_batch_variables_must_be_complete(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for prefix in ("%", "~", "."):  # a password that merely starts like a path or a batch variable
            self.assertTrue(r.scan_for_secrets(diff_adding("config.yml", "PWD" + ': "' + prefix + pw + '"')), prefix)
        for path, line in [("env.bat", "set PWD=%CD%"), ("env.bat", "set PWD=%USERPROFILE%\\project-workspace"), ("env.sh", "PWD=~/project-workspace-one"),
                           ("env.sh", "PWD=./project-workspace-one"), ("env.sh", "PWD=$(pwd)")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_a_comment_after_a_multiline_call_opener(self):
        pw = "A1!correct-horse-" + "battery-staple"
        diff = diff_adding("c.py", "API_" + "KEY = os.getenv(  # allow local override", '    "API_KEY",', '    "' + pw + '",', ")")
        self.assertEqual([(w, ln) for w, ln, _ in r.scan_for_secrets(diff)], [("c.py", 4)])
        diff = diff_adding("c.js", "const API_" + "KEY = getKey(  // note", '    "API_KEY",', '    "' + pw + '",  // fallback', ")")
        self.assertTrue(r.scan_for_secrets(diff))
        # comments between the concatenated fragments do not break the chain
        diff = diff_adding("c.py", "API_" + "KEY = (", '    "A1!correct-"  # first half', '    "horse-battery-staple"  # second half', ")")
        self.assertTrue(r.scan_for_secrets(diff))

    def test_multiline_state_starts_only_for_assignments(self):
        for opener in ("if API_" + "KEY == settings.get(", "if API_" + "KEY != settings.get(", "if API_" + "KEY <= settings.get(", "while API_" + "KEY >= settings.get("):
            diff = diff_adding("c.py", opener, '    "API_KEY",', '    "development-v2",', "):")
            self.assertEqual(r.scan_for_secrets(diff), [], opener)
        diff = diff_adding("c.py", "API_" + "KEY = settings.get(", '    "API_KEY",', '    "development-v2-staging",', ")")
        self.assertTrue(r.scan_for_secrets(diff))  # the same lines as an assignment ARE a credential-named default

    def test_secret_store_references_with_embedded_credentials(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for line in ("DATABASE_" + "SECRET=vault://admin:" + pw + "@vault.example/secret/db",
                     "DATABASE_" + "SECRET=ref+vault://x/y?api_key=abcdefghij" + "klmnop"):
            self.assertTrue(r.scan_for_secrets(diff_adding(".env", line)), line)
        for line in ("DATABASE_" + "SECRET=vault://vault.example/secret/db", "DATABASE_" + "SECRET=op://vault/db/password"):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)

    def test_url_parameter_prefixes_are_matched_as_whole_words(self):
        line = "API_" + "KEY_URL=https://docs.example/search?author_key=shakespeare"
        self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)
        for param in ("auth_key", "authorization_key", "x-session-key"):
            line = "API_" + "KEY_URL=https://docs.example/search?" + param + "=abcdefghij" + "klmnop"
            self.assertTrue(r.scan_for_secrets(diff_adding(".env", line)), param)

    def test_strip_source_comment_follows_source_syntax(self):
        for line, expected in [('x = f("a # b",  # note', 'x = f("a # b",'), ('API_KEY = os.getenv(  # read "API_KEY" override', "API_KEY = os.getenv("),
                               ("x = f(  # it's here", "x = f("), ("x = f('a//b'", "x = f('a//b'"),
                               ("x = f(y#z", "x = f(y#z"), ("# whole line", ""), ('x = "unclosed # still a string', 'x = "unclosed # still a string')]:
            self.assertEqual(r.strip_source_comment(line), expected, line)
        self.assertEqual(r.strip_source_comment("x = f(  // a `b` c", "//"), "x = f(")

    def test_a_quoted_name_in_a_comment_after_a_multiline_call_opener(self):
        pw = "A1!correct-horse-" + "battery-staple"
        diff = diff_adding("c.py", "API_" + 'KEY = os.getenv(  # read "API_KEY" override', '    "API_KEY",', '    "' + pw + '",', ")")
        self.assertEqual([(w, ln) for w, ln, _ in r.scan_for_secrets(diff)], [("c.py", 4)])

    def test_a_completed_batch_variable_must_be_followed_only_by_a_path(self):
        pw = "A1!correct-horse-" + "battery-staple"
        self.assertTrue(r.scan_for_secrets(diff_adding("config.yml", "PWD" + ': "%CD%' + pw + '"')))
        for path, line in [("env.bat", "set PWD=%CD%"), ("env.bat", "set PWD=%CD%\\project-workspace"), ("env.bat", "set PWD=%CD%/project-workspace")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_f_string_lookup_keys_are_exempt_only_for_known_lookups(self):
        secret, key, open_, close = "A1correct-horse-" + "battery-staple", "API_KEY", "('", "')}\""
        for call in ("str", "bytes", "decode", "SecretStr", "wrap"):
            line = "API_" + "KEY = f\"{" + call + open_ + secret + close
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), call)
        for call in ("os.getenv", "settings.get", "get_secret", "config.getint", "os.environ.pop"):
            line = "API_" + "KEY = f\"{" + call + open_ + key + close
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], call)

    def test_f_string_interpolation_is_a_reference_inside_a_metadata_url(self):
        for line in ("API_" + 'KEY = Credential(url=f"https://host/cb?client_secret={settings.CLIENT_SECRET}")',
                     "API_" + 'KEY = Credential(url=f"https://user:{settings.DB_PW}@host/db")',
                     "API_" + 'KEY_URL = URL(f"https://host/cb?client_secret={settings.CLIENT_SECRET}")'):  # a metadata-NAMED variable
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)
        # the same holds for a name that is not a setting: an interpolated credential parameter is a reference
        for line in ("API_" + 'KEY = URL(f"https://host/cb?client_secret={settings.CLIENT_SECRET}")',
                     "API_" + 'KEY = f"https://host/cb?client_secret={settings.CLIENT_SECRET}&x={y[0]}"',
                     "API_" + 'KEY = f"https://user:{db.password!s}@host/db"'):
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)
        # a literal credential in the same f-string is still found, and so is one in a plain (non-f) string
        for line in ("API_" + 'KEY = f"https://host/cb?client_secret=abcde' + 'fghijklmnop&x={y}"',
                     "API_" + 'KEY = Credential(url=f"https://host/cb?client_secret=abcde' + 'fghijklmnop&x={y}")',
                     "API_" + 'KEY = Credential(url="https://host/cb?client_secret={set' + 'tings.CLIENT_SECRET}x")'):
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_a_comment_directly_after_an_opening_bracket(self):
        for line, expected in [("x = f(# note", "x = f("), ("x = {# c", "x = {"), ("x = a,# c", "x = a,"), ("x = a#b", "x = a#b"),
                               ('x = f("a#b")', 'x = f("a#b")')]:
            self.assertEqual(r.strip_source_comment(line), expected, line)
        pw = "A1!correct-horse-" + "battery-staple"
        diff = diff_adding("c.py", "API_" + "KEY = os.getenv(# read override", '    "API_KEY",', '    "' + pw + '",', ")")
        self.assertEqual([(w, ln) for w, ln, _ in r.scan_for_secrets(diff)], [("c.py", 4)])

    def test_comment_syntax_follows_the_files_language(self):
        self.assertEqual(r.comment_markers("a/b.py"), "#")
        self.assertEqual(r.comment_markers("a/b.sh"), "#")
        self.assertEqual(r.comment_markers("a/b.ts"), "//")
        self.assertEqual(r.comment_markers("a/b.php"), "#//")
        self.assertEqual(r.strip_source_comment("keys[len(keys) // 2])", "#"), "keys[len(keys) // 2])")
        self.assertEqual(r.strip_source_comment("keys[len(keys) // 2])", "//"), "keys[len(keys)")
        # Python floor division must not swallow the closing parenthesis and leave the state open for an unrelated line
        diff = diff_adding("c.py", "API_" + "KEY = select(", "    keys[len(keys) // 2])", 'release = "release-2026.10"')
        self.assertEqual(r.scan_for_secrets(diff), [])
        # in a C-like file `//` is a comment
        pw = "A1!correct-horse-" + "battery-staple"
        diff = diff_adding("c.js", "const API_" + "KEY = getKey(  // note", '    "API_KEY",', '    "' + pw + '",', ")")
        self.assertTrue(r.scan_for_secrets(diff))

    def test_literals_inside_spaced_f_string_expressions(self):
        payload = "A1correct-horse-" + "battery-staple"
        for call in ("str", "bytes", "wrap"):
            line = "API_" + "KEY = f\"{" + call + "( '" + payload + "' )}\""
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), call)
        line = "API_" + "KEY = f\"{os.getenv( 'API_KEY', '" + payload + "' )}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        for call in ("os.getenv", "settings.get", "get_secret"):
            line = "API_" + "KEY = f\"{" + call + "( 'API_KEY' )}\""
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], call)

    def test_a_literal_username_survives_an_interpolated_password(self):
        payload = "A1!correct-horse-" + "battery-staple"
        line = "API_" + 'KEY = f"https://' + payload + ':{db.password}@host"'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        for user in ("svc-account", "postgres", "app_user", "svc-account-01"):
            line = "API_" + 'KEY = f"https://' + user + ':{db.password}@host/db"'
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], user)

    def test_conventional_lookup_spellings(self):
        key, open_, close = "API_KEY", "('", "')}\""
        for call in ("get_config", "get_setting", "get_option", "read_config", "load_config", "get_value"):
            line = "API_" + "KEY = f\"{" + call + open_ + key + close
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], call)

    def test_batch_script_directory_expansions(self):
        for path, line in [("env.bat", "set PWD=%~dp0project-workspace"), ("env.bat", "set PWD=%~dp0"), ("env.bat", "set PWD=%~f0\\project"),
                           ("env.bat", "set PWD=%~p0")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))
        pw = "A1!correct-horse-" + "battery-staple"
        self.assertTrue(r.scan_for_secrets(diff_adding("config.yml", "PWD" + ': "%~dp0' + pw + '"')))

    def test_groovy_gradle_and_jenkinsfile_use_slash_comments(self):
        for path, markers in [("build.gradle", "//"), ("src/Foo.groovy", "//"), ("Jenkinsfile", "//"), ("ci/Jenkinsfile.prod", "//"),
                              ("api.proto", "//"), ("main.tf", "#//"), ("vars.hcl", "#//"), ("app.py", "#"), ("deploy.sh", "#")]:
            self.assertEqual(r.comment_markers(path), markers, path)
        pw = "A1!correct-horse-" + "battery-staple"
        for path in ("build.gradle", "Jenkinsfile", "src/Foo.groovy"):
            diff = diff_adding(path, "API_" + "KEY = getKey( // allow local override", '    "API_KEY",', '    "' + pw + '",', ")")
            self.assertTrue(r.scan_for_secrets(diff), path)

    def test_the_first_argument_of_an_unknown_call_in_an_f_string_is_the_value(self):
        for call in ("str", "bytes", "wrap", "SomeWrapper"):
            line = "API_" + "KEY = f\"{" + call + "( 'correct-horse-" + "battery-staple' )}\""
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), call)
        key, open_, close = "some-lookup-key-name", "( '", "' )}\""
        for call in ("os.getenv", "settings.get", "config", "get_secret"):
            line = "API_" + "KEY = f\"{" + call + open_ + key + close
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], call)

    def test_a_lowercase_passphrase_username_is_not_plain(self):
        for user in ("correct-horse-battery-staple", "horse-battery-staple-correct"):
            line = "API_" + 'KEY = f"https://' + user + ':{db.password}@host"'
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), user)
        for user in ("svc-account", "postgres", "app_user", "svc-account-readonly"):
            line = "API_" + 'KEY = f"https://' + user + ':{db.password}@host/db"'
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], user)

    def test_the_working_directory_value_must_be_entirely_path_characters(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for prefix in ("%~dp0\\", "%CD%\\", "/", "~/", "./", "C:\\"):
            line = "PWD" + ': "' + prefix + pw + '"'
            self.assertTrue(r.scan_for_secrets(diff_adding("config.yml", line)), prefix)
        for path, line in [("env.sh", "PWD=/home/user/project-workspace"), ("env.sh", "PWD=~"), ("env.sh", "PWD=.."), ("env.bat", "set PWD=%CD%\\a\\b"),
                           ("env.bat", "set PWD=C:\\Users\\dev\\project"), ("env.bat", "set PWD=\\\\server\\share\\project")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_nested_f_strings_inside_an_interpolation(self):
        payload = "A1correct-horse-" + "battery-staple"
        line = "API_" + "KEY = f\"{os.getenv('API_KEY', f'{prefix}-" + payload + "')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        key, tail = "API_KEY", "{suffix}')}\""
        line = "API_" + "KEY = f\"{os.getenv('" + key + "', f'{prefix}-" + tail
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)
        self.assertEqual(r.fstring_expressions("a{f(g'{x}')}b{y}"), ["f(g'{x}')", "y"])
        self.assertEqual(r.fstring_expressions("{{literal}}{real}"), ["real"])

    def test_groovy_slashy_strings_are_literals(self):
        for path, line in [("build.gradle", "API_" + "KEY = /correct-horse-" + "battery-staple/"), ("Jenkinsfile", "API_" + "KEY = $/correct-horse-" + "battery-staple/$"),
                           ("src/Foo.groovy", "API_" + "KEY = /Zx9Yw8Vu7Ts6" + "Rq5Po4Nm3/")]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        for path, line in [("build.gradle", "API_" + "KEY = /^[a-z0-9]{20}$/"), ("app.js", "API_" + "KEY = /[A-Za-z0-9]+/"),
                           ("build.gradle", "API_" + 'KEY = System.getenv("API_KEY")')]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_long_role_usernames_are_plain_but_hyphenated_passphrases_are_not(self):
        for user in ("application_readonly_user", "svc-account-readonly", "postgres_application_owner"):
            line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], user)
        for user in ("correct-horse-battery-staple", "horse-battery-staple-correct-mule"):
            line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), user)

    def test_working_directory_paths_with_ordinary_punctuation_and_required_separators(self):
        for path, line in [("env.sh", "PWD=/home/dev/c++"), ("env.sh", "PWD=/home/dev/user@host"), ("env.sh", "PWD=~/projects/my-app_v2"),
                           ("env.bat", "set PWD=%~dp0project-workspace"), ("env.bat", "set PWD=%CD%\\apps\\c++")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))
        for value in ("~correct-horse-battery-staple", "%CD%correct-horse-battery-staple", ".correct-horse-battery-staple",
                      "..correct-horse-battery-staple", "%~f0correct-horse-battery-staple"):
            self.assertTrue(r.scan_for_secrets(diff_adding("env.sh", "PWD=" + value)), value)

    def test_braces_inside_quoted_strings_do_not_balance_interpolations(self):
        self.assertEqual(r.fstring_expressions("{a['}']}b"), ["a['}']"])
        self.assertEqual(r.fstring_expressions("{os.getenv('K}', f'{x}')}"), ["os.getenv('K}', f'{x}')"])
        self.assertEqual(r.fstring_expressions("literal ' quote {x} here"), ["x"])
        payload = "A1correct-horse-" + "battery-staple"
        line = "API_" + "KEY = f\"{os.getenv('API_KEY}', '" + payload + "')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))

    def test_typed_getters_and_other_lookup_families_are_lookups(self):
        key, open_, close = "service-api-key", "('", "')}\""
        for call in ("config.get_string", "settings.getLong", "get_int", "load_setting", "fetch_param", "find_value", "lookup_key", "read_value"):
            line = "API_" + "KEY = f\"{" + call + open_ + key + close
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], call)
        self.assertTrue(r.is_lookup_call("os.environ.get") and r.is_lookup_call("getenv") and not r.is_lookup_call("str"))

    def test_lowercase_credential_names_with_quoted_literals_in_source_files(self):
        pw = "A1!correct-horse-" + "battery"
        for path in ("build.gradle", "app.py", "app.js", "Foo.java"):
            line = "database_" + 'password = "' + pw + '"'
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), path)
        for path, line in [("app.py", "password = os.environ['DATABASE_PASSWORD_PRIMARY']"), ("app.py", 'token = "Bearer"'),
                           ("app.py", 'password_prompt = "Enter password: "'), ("app.py", 'secret_name = "billing-service-secret"'),
                           ("build.gradle", "password = project.findProperty('dbPassword')")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_groovy_slashy_strings_may_hold_punctuation(self):
        for path, line in [("build.gradle", "API_" + "KEY = /A1!correct-horse-" + "battery-staple/"), ("Jenkinsfile", "API_" + "KEY = $/A1!correct-horse-" + "battery-staple/$")]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        for value in ("^[a-z0-9]{20}$", "[A-Za-z0-9]+", "(?:abc|def)ghijkl", r"\d+\.\d+\.\d+abc", "abc.*defghijk"):
            self.assertTrue(r.REGEX_LIKE_RE.search(value), value)
        self.assertFalse(r.REGEX_LIKE_RE.search("A1!correct-horse-battery-staple"))
        self.assertEqual(r.scan_for_secrets(diff_adding("build.gradle", "API_" + "KEY = /^[a-z0-9]{20}$/")), [])

    def test_underscore_delimited_passphrase_usernames_are_not_plain(self):
        for user in ("correct_horse_battery_staple", "correct-horse_battery-staple"):
            line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), user)
        for user in ("application_readonly_user", "postgres_application_owner", "svc-account-readonly"):
            line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], user)

    def test_value_consuming_helpers_are_not_lookups(self):
        for call in ("get_hashed_password", "read_and_encrypt", "load_credentials_from", "fetch_token_for", "find_user_hash"):
            self.assertFalse(r.is_lookup_call(call), call)
        for call in ("get_string", "getLong", "load_setting", "fetch_param", "os.getenv", "settings.get", "config", "lookup_key"):
            self.assertTrue(r.is_lookup_call(call), call)
        line = "PASSWORD_" + "HASH = f\"{get_hashed_password('correct-horse-" + "battery-staple')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))

    def test_quoted_working_directories_may_hold_a_hash(self):
        for path, line in [("env.sh", 'PWD="/home/dev/c#"'), ("env.sh", "PWD='/home/dev/f#/src'"), ("env.sh", 'OLDPWD="/home/dev/c#-projects"')]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_a_value_that_names_a_credential_field_is_not_a_credential(self):
        for line in ("token_" + 'key = "access_token"', "secret_" + 'field = "client_secret"', "password_" + 'field = "password"',
                     "refresh_" + 'token_name = "refresh_token"', "auth_" + 'header = "Authorization"'):
            self.assertEqual(r.scan_for_secrets(diff_adding("oauth.py", line)), [], line)
        self.assertTrue(r.scan_for_secrets(diff_adding("oauth.py", "token_" + 'value = "access_token_A1!correct-horse"')))

    def test_triple_quoted_literals_inside_f_string_expressions(self):
        self.assertEqual(r.fstring_expressions("{os.getenv('''API'KEY}''', 'x')}"), ["os.getenv('''API'KEY}''', 'x')"])
        self.assertEqual(r.fstring_expressions('{f("""a"b}""")}'), ['f("""a"b}""")'])
        self.assertEqual(r.fstring_expressions("{a['']}{b}"), ["a['']", "b"])
        payload = "A1correct-horse-" + "battery-staple"
        line = "API_" + "KEY = f\"{os.getenv('''API'KEY}''', '" + payload + "')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))

    def test_a_lone_regex_character_does_not_make_a_slashy_credential_a_regex(self):
        for value in ("^abcdefghijkl$", "^[a-z0-9]{20}$", "[A-Za-z0-9]+", "(?:abc|def)ghijkl", r"\d+\.\d+\.\d+abc", "abc.*defghijk"):
            self.assertTrue(r.REGEX_LIKE_RE.search(value), value)
        for value in ("A1!correct-horse-battery-staple$", "^A1!correct-horse-battery-staple", "A1!correct(horse)battery-staple"):
            self.assertFalse(r.REGEX_LIKE_RE.search(value), value)
        for slashy in ("A1!correct-horse-battery-staple$", "^A1!correct-horse-battery-staple"):
            self.assertTrue(r.scan_for_secrets(diff_adding("build.gradle", "API_" + "KEY = /" + slashy + "/")), slashy)

    def test_four_word_role_usernames_with_a_role_word_are_plain(self):
        for user in ("my_application_readonly_user", "svc_account_readonly_user", "prod-db-readonly-user", "analytics_etl_batch_worker"):
            line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], user)
        for user in ("correct_horse_battery_staple", "purple_monkey_dishwasher_cactus"):
            line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), user)

    def test_password_and_credential_getters_are_lookups(self):
        for call in ("keyring.get_password", "read_password", "get_passwords", "keyring.get_credential", "keychain.get_credentials"):
            self.assertTrue(r.is_lookup_call(call), call)
        for call in ("get_hashed_password", "oauth.get_token", "getToken", "get_api_key", "oauth.get_credentials", "get_credentials"):
            self.assertFalse(r.is_lookup_call(call), call)  # these may consume an existing credential
        key, user, open_, close = "service-api-key", "deploy-user", "( '", "' )}\""
        line = "API_" + "KEY = f\"{keyring.get_password" + open_ + key + "', '" + user + close
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_a_field_name_value_is_exempt_only_under_a_descriptor_name(self):
        for name in ("TOKEN_KEY", "secret_field", "AUTH_HEADER", "oauth.token.name", "REFRESH_TOKEN_ATTR"):
            self.assertTrue(r.descriptor_name(name), name)
        for name in ("DATABASE_PASSWORD", "api_secret", "ACCESS_TOKEN", "db.password"):
            self.assertFalse(r.descriptor_name(name), name)
        for line in ("DATABASE_" + 'PASSWORD = "author' + 'ization"', "database_" + 'password = "author' + 'ization"',
                     "ACCESS_" + 'TOKEN = "refresh_' + 'token"'):
            self.assertTrue(r.scan_for_secrets(diff_adding("config.py", line)), line)
        for line in ("token_" + 'key = "access_token"', "secret_" + 'field = "client_secret"'):
            self.assertEqual(r.scan_for_secrets(diff_adding("oauth.py", line)), [], line)

    def test_escaped_triple_delimiters_inside_f_string_expressions(self):
        payload = "A1correct-horse-" + "battery-staple"
        line = "API_" + "KEY = f\"{os.getenv('''API\\'''KEY}''', '" + payload + "')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        self.assertEqual(r.fstring_expressions("{a('''x\\'''}''')}"), ["a('''x\\'''}''')"])

    def test_a_role_name_is_mostly_role_words(self):
        for user in ("my_application_readonly_user", "svc_account_readonly_user", "prod-db-readonly-user", "analytics_etl_batch_worker",
                     "payments_app_ro_user", "reports_bi_rw_user"):
            self.assertTrue(r.plain_username(user), user)
        for user in ("correct_horse_admin_staple", "correct_admin_root_staple", "purple_monkey_dishwasher_cactus",
                     "correct-horse-battery-staple", "a_b_c_user_x_y"):
            self.assertFalse(r.plain_username(user), user)
        user = "correct_horse_" + "admin_staple"
        line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))

    def test_token_getters_may_consume_a_credential(self):
        line = "ACCESS_" + "TOKEN = f\"{oauth.get_token('rt-correct-horse-" + "battery-staple')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        key, open_, close = "service-api-key", "('", "')}\""
        line = "API_" + "KEY = f\"{keyring.get_password" + open_ + key + close
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_alias_and_reference_names_are_descriptors(self):
        for name in ("token_alias", "SECRET_REF", "API_KEY_REFERENCE", "password_tag", "AUTH_SYMBOL"):
            self.assertTrue(r.descriptor_name(name), name)
        self.assertEqual(r.scan_for_secrets(diff_adding("oauth.py", "token_" + 'alias = "access_token"')), [])

    def test_a_capturing_group_with_alternation_is_regex_structure(self):
        for value in ("(identifier|string|number)", "identifier|string|number", "(foo|bar|baz)", "(sha1|sha256|md5)",
                      "(NUMBER|STRING|IDENT)", "(Identifier|String|Number)"):
            self.assertTrue(r.REGEX_LIKE_RE.search(value), value)
        for value in ("(A1b2|C3d4|E5f6)", "(a1B2|c3D4)", "(Xk9|Qw3)"):  # mixed case with digits: credential-shaped
            self.assertFalse(r.REGEX_LIKE_RE.search(value), value)
        self.assertTrue(r.scan_for_secrets(diff_adding("build.gradle", "API_" + "KEY = /(A1b2|C3d4" + "|E5f6)/")))
        for value in ("A1!correct(horse)battery-staple", "A1!prod(us|eu)db-password", "(us|eu)db-password-1"):
            self.assertFalse(r.REGEX_LIKE_RE.search(value), value)
        self.assertTrue(r.scan_for_secrets(diff_adding("build.gradle", "API_" + "KEY = /A1!prod(us|eu)" + "db-password/")))
        self.assertEqual(r.scan_for_secrets(diff_adding("src/Lexer.groovy", "TOKEN = /(identifier|string|number)/")), [])

    def test_kotlin_raw_strings_have_no_escapes(self):
        payload = "A1correct-horse-" + "battery-staple"
        line = "API_" + 'KEY = lookup("""name\\""", "' + payload + '")'
        self.assertTrue(r.scan_for_secrets(diff_adding("Foo.kt", line)))
        # Python's escaped triple delimiter is still read as an escape
        line = "API_" + "KEY = f\"{os.getenv('''API\\'''KEY}''', '" + payload + "')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))
        # inside an f-string expression the same ambiguity is read both ways: only the escape-free reading ends the key early
        line = "API_" + "KEY = f\"{lookup('''name\\''', '" + payload + "')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)))

    def test_windows_paths_are_not_credential_punctuation(self):
        for value in ("C:\\Users\\me\\.ssh\\", "D:/work/keys/", "\\\\server\\share\\keys\\"):
            self.assertTrue(r.WINDOWS_PATH_RE.fullmatch(value), value)
        self.assertFalse(r.WINDOWS_PATH_RE.fullmatch("A1!correct-horse-battery-staple"))
        line = "PRIVATE_" + 'KEY = Path.of("""C:\\Users\\me\\.ssh\\""", "id_rsa")'
        self.assertEqual(r.scan_for_secrets(diff_adding("Keys.kt", line)), [], line)

    def test_credential_store_getters_return_the_credential_not_consume_one(self):
        key, user, open_, close = "service-api-key", "deploy-user", "( '", "' ).password}\""
        line = "API_" + "KEY = f\"{keyring.get_credential" + open_ + key + "', '" + user + close
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_a_windows_path_is_exempt_only_as_a_lookup_key(self):
        payload = "correct-horse-" + "battery-staple"
        line = "API_" + 'KEY = SecretStr(r"C:\\' + payload + '")'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)
        line = "API_" + 'KEY = os.getenv("API_KEY", r"C:\\' + payload + '")'  # a fallback that IS the credential
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_credential_getters_are_lookups_only_on_known_credential_stores(self):
        payload = "correct-horse-" + "battery-staple"
        line = "ACCESS_" + "TOKEN = f\"{oauth.get_credentials('" + payload + "')}\""
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)
        key, open_, close = "service-api-key", "('", "')}\""
        line = "API_" + "KEY = f\"{keyring.get_credential" + open_ + key + close
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_digit_bearing_alternation_regexes_and_role_abbreviations(self):
        self.assertEqual(r.scan_for_secrets(diff_adding("src/Lexer.groovy", "TOKEN = /(sha1|sha256|md5)/")), [])
        self.assertTrue(r.scan_for_secrets(diff_adding("build.gradle", "API_" + "KEY = /A1!prod(us|eu)" + "db-password/")))
        line = "DATABASE_" + 'SECRET = f"postgresql://payments_app_ro_user:{db.password}@host/db"'
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_abbreviations_alone_do_not_make_a_role_name(self):
        for user in ("correct_bi_ml_dw", "purple_bi_dw_ml", "horse_bi_dw_ml"):
            self.assertFalse(r.plain_username(user), user)
        for user in ("payments_app_ro_user", "reports_bi_rw_user", "etl_dw_ro_reader"):
            self.assertTrue(r.plain_username(user), user)
        user = "correct_bi_" + "ml_dw"
        line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_snake_case_credential_store_receivers(self):
        for call in ("credential_store.get_credentials", "cred_store.get_credential", "credentialstore.get_password", "self.keyring.get_password"):
            self.assertTrue(r.is_lookup_call(call), call)
        self.assertFalse(r.is_lookup_call("oauth.get_credentials"))
        key, open_, close = "service-api-key", "('", "')}\""
        line = "API_" + "KEY = f\"{credential_store.get_credentials" + open_ + key + close
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_a_windows_path_needs_a_path_or_lookup_callee(self):
        payload = "correct-horse-" + "battery-staple"
        for call in ("encrypt", "hash_value", "wrap"):
            line = "API_" + "KEY = " + call + '(r"C:\\' + payload + '")'
            self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), call)
        for call in ("Path", "os.path.join", "File", "open", "Paths.get", "os.getenv"):
            line = "API_" + "KEY = " + call + '(r"C:\\Users\\me\\.ssh")'
            self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], call)

    def test_two_strong_service_abbreviations_make_a_role(self):
        for user in ("billing_svc_ro_dba", "orders_svc_rw_adm", "svc_ro_usr_x"):
            self.assertTrue(r.plain_username(user), user)
        for user in ("correct_bi_ml_dw", "correct_svc_staple_x"):
            self.assertFalse(r.plain_username(user), user)

    def test_camel_case_alternation_regexes(self):
        for value in ("(accessToken|refreshToken|idToken)", "(userName|passWord)"):
            self.assertTrue(r.REGEX_LIKE_RE.search(value), value)
        for value in ("(xK9|qW3)", "(aB1|cD2)", "(A1b2|C3d4|E5f6)"):
            self.assertFalse(r.REGEX_LIKE_RE.search(value), value)
        self.assertEqual(r.scan_for_secrets(diff_adding("src/Lexer.groovy", "TOKEN = /(accessToken|refreshToken|idToken)/")), [])

    def test_private_credential_store_receivers(self):
        for call in ("self._credential_store.get_credentials", "self.__keyring.get_password", "_cred_store.get_credential"):
            self.assertTrue(r.is_lookup_call(call), call)
        key, open_, close = "service-api-key", "('", "')}\""
        line = "API_" + "KEY = f\"{self._credential_store.get_credentials" + open_ + key + close
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_path_callees_are_matched_by_complete_component(self):
        for call in ("Path.of", "os.path.join", "shutil.copy", "Files.readString", "File", "open", "getFilePath", "dir_util.copy_tree",
                     "pathlib.Path", "loadPEMFile", "readSSHKeyFile", "os.remove", "remove", "os.rename"):
            self.assertTrue(r.is_path_call(call), call)
        for call in ("profile.encrypt", "encrypt", "hash_value", "wrap", "dirty.mix", "filesystem_secret.wrap", "credentials.remove",
                     "keys.join", "cache.resolve", "os.getenv"):
            self.assertFalse(r.is_path_call(call), call)
        payload = "correct-horse-" + "battery-staple"
        line = "API_" + 'KEY = profile.encrypt(r"C:\\' + payload + '")'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)
        line = "PRIVATE_" + 'KEY = shutil.copy(r"C:\\Users\\me\\.ssh\\id_rsa", tmpdir)'
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", line)), [], line)

    def test_short_camel_case_components_in_alternations(self):
        for value in ("(userId|groupId|accountId)", "(getId|setId)", "(accessToken|userId)", "(userID|groupID|accountID)", "(getURL|setURL)"):
            self.assertTrue(r.REGEX_LIKE_RE.search(value), value)
        for value in ("(xK9|qW3)", "(A1b2|C3d4|E5f6)", "(aB1|cD2)"):
            self.assertFalse(r.REGEX_LIKE_RE.search(value), value)
        self.assertEqual(r.scan_for_secrets(diff_adding("src/Lexer.groovy", "TOKEN = /(userId|groupId|accountId)/")), [])

    def test_repeated_role_abbreviations_are_not_corroboration(self):
        for user in ("correct_ro_ro_ro", "purple_svc_svc_svc", "bi_ml_ro_ro"):
            self.assertFalse(r.plain_username(user), user)
        for user in ("billing_svc_ro_dba", "payments_app_ro_user", "svc_ro_usr_x", "billing_svc_svc_user"):
            self.assertTrue(r.plain_username(user), user)
        user = "correct_ro_" + "ro_ro"
        line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_later_path_arguments_of_filesystem_calls(self):
        for line in ("PRIVATE_" + 'KEY = shutil.copy(src, r"C:\\Users\\me\\.ssh\\id_rsa")', "PRIVATE_" + 'KEY = loadPEMFile(r"C:\\Users\\me\\.ssh\\id_rsa")',
                     "PRIVATE_" + 'KEY = Files.copy(src, Paths.get(r"C:\\Users\\me\\.ssh\\id_rsa"))'):
            self.assertEqual(r.scan_for_secrets(diff_adding("keys.py", line)), [], line)
        payload = "correct-horse-" + "battery-staple"
        # a collection method named like a filesystem operation consumes the value
        line = "val API_" + 'KEY = credentials.remove("""C:\\' + payload + '""")'
        self.assertTrue(r.scan_for_secrets(diff_adding("Creds.kt", line)), line)
        # and a fallback that is the credential stays a credential even next to a lookup
        line = "API_" + 'KEY = os.getenv("API_KEY", r"C:\\' + payload + '")'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_known_limit_camel_case_identifier_alternations_look_like_lexer_rules(self):
        # (correctId|batteryId) and (userId|groupId) have the same shape; the lexer-rule reading is chosen (documented limit)
        self.assertTrue(r.REGEX_LIKE_RE.search("(correctId|batteryId)"))
        self.assertTrue(r.REGEX_LIKE_RE.search("(userId|groupId)"))

    def test_only_path_operations_take_later_path_arguments(self):
        for call in ("shutil.copy", "Files.copy", "os.rename", "Paths.get", "os.path.join", "Path.of", "filesystem.resolve"):
            self.assertTrue(r.takes_path_arguments(call), call)
        for call in ("ssh.openPrivateKey", "loadPEMFile", "open", "File.readString", "keystore.loadKey"):
            self.assertFalse(r.takes_path_arguments(call), call)
        payload = "correct-horse-" + "battery-staple"
        line = "PRIVATE_" + 'KEY = ssh.openPrivateKey("id_rsa", r"C:\\' + payload + '")'  # the second literal is the passphrase
        self.assertTrue(r.scan_for_secrets(diff_adding("keys.py", line)), line)
        line = "PRIVATE_" + 'KEY = filesystem.resolve(r"C:\\Users\\me\\.ssh\\id_rsa")'
        self.assertEqual(r.scan_for_secrets(diff_adding("keys.py", line)), [], line)

    def test_one_repeated_role_word_is_not_a_role(self):
        for user in ("correct_admin_admin_admin", "purple_user_user_user", "x_service_service_service"):
            self.assertFalse(r.plain_username(user), user)
        for user in ("billing_svc_svc_user", "payments_app_app_user"):
            self.assertTrue(r.plain_username(user), user)
        user = "correct_admin_" + "admin_admin"
        line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_numbered_operations_are_listed_by_name_not_normalised(self):
        self.assertEqual(r.callee_words("shutil.copy2"), ["shutil", "copy2"])
        self.assertTrue(r.takes_path_arguments("shutil.copy2"))
        # known numbered filesystem APIs are listed by name, bare or module-qualified
        for call in ("copy2", "shutil.copy2", "_stat64", "_wstat64", "os.stat64", "_stat", "_wstat", "_stat32", "_wstat32",
                     "_stati64", "_wstati64", "_stat32i64", "_stat64i32", "_wstat32i64", "_wstat64i32"):
            self.assertTrue(r.is_path_call(call), call)
        for line, path in [("PRIVATE_" + 'KEY = copy2(r"C:\\Users\\me\\.ssh\\id_rsa", tmpdir)', "keys.py"),
                           ("int PRIVATE_" + 'KEY_STATUS = _stat64("C:\\\\Users\\\\me\\\\.ssh\\\\id_rsa", &info);', "keys.c"),
                           ("int PRIVATE_" + 'KEY_STATUS = _stat64i32("C:\\\\Users\\\\me\\\\.ssh\\\\id_rsa", &info);', "keys.c")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], line)
        # an arbitrary versioned helper does not inherit filesystem semantics
        for call in ("resolve2", "join2", "remove_v2", "cache.copy2"):
            self.assertFalse(r.is_path_call(call), call)
        payload = "correct-horse-" + "battery-staple"
        line = "API_" + 'KEY = resolve2(r"C:\\' + payload + '")'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)
        line = "PRIVATE_" + 'KEY = shutil.copy2(temp_key, r"C:\\Users\\me\\.ssh\\id_rsa")'
        self.assertEqual(r.scan_for_secrets(diff_adding("keys.py", line)), [], line)

    def test_write_create_and_replace_take_data_not_a_path(self):
        for call in ("Files.write", "Files.createFile", "text.replace", "Files.writeString"):
            self.assertFalse(r.takes_path_arguments(call), call)
        payload = "A1correct-horse-" + "battery-staple"
        line = "Path PRIVATE_" + 'KEY = Files.write(keyPath, "C:\\\\' + payload + '".getBytes(UTF_8));'
        self.assertTrue(r.scan_for_secrets(diff_adding("Keys.java", line)), line)

    def test_role_aliases_count_once(self):
        for user in ("correct_admin_adm_staple_admin", "purple_svc_service_service", "x_usr_user_users"):
            self.assertFalse(r.plain_username(user), user)
        for user in ("billing_svc_ro_dba", "payments_app_ro_user", "prod-db-readonly-user", "orders_svc_rw_adm", "svc_ro_usr_x",
                     "billing_svc_svc_user", "my_application_readonly_user"):
            self.assertTrue(r.plain_username(user), user)
        user = "correct_admin_adm_" + "staple_admin"
        line = "DATABASE_" + 'SECRET = f"postgresql://' + user + ':{db.password}@host/db"'
        self.assertTrue(r.scan_for_secrets(diff_adding("c.py", line)), line)

    def test_numeric_credentials_are_caught(self):
        for path, line in [("config.py", "api_" + 'key = "1234567890' + '1234567890"'), (".env", "API_" + 'KEY="1234567890' + '1234567890"'),
                           (".env", "DATABASE_" + "PASSWORD=1234-5678-" + "9012-3456")]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))
        # a version number next to a real placeholder word is still a placeholder
        self.assertEqual(r.scan_for_secrets(diff_adding(".env", "API_" + "KEY=your_api_key_v2")), [])

    def test_namespaced_credential_query_parameters_are_not_exempt(self):
        for param in ("client_secret", "refresh_token", "access_token", "id_token", "x-api-key", "oauth.token", "api_key"):
            value = "https://auth.internal/cb?" + param + "=abcdefghijklmnopqrstuvwxyz"
            self.assertFalse(r.non_secret_literal(value), value)  # all letters: no digit to trip the token-shape check
        for harmless in ("https://auth.internal/cb?page=abcdefghijklmnopqrstuvwxyz", "https://x.org/a?monkeys=abcdefghij",
                         "https://auth.internal/cb?state=ready"):
            self.assertTrue(r.non_secret_literal(harmless), harmless)

    def test_metadata_suffixes_are_settings_not_credentials(self):
        for line in ("TOKEN_EXPIRY_" + "POLICY=slidingexpiration", "PASSWORD_MIN_" + "REQUIREMENTS=minimumtwelvechars",
                     "API_KEY_" + "FILE=somewhere-local-keyfile", "SECRET_" + "KEY_PATH=local-secret-location-name",
                     "TOKEN_" + "ENDPOINT=authorization-service-name", "PASSWORD_" + "POLICY: strict-rotation-quarterly"):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)
        # qualifiers that are not metadata still count (an unknown suffix fails closed)
        for line in ("DATABASE_" + "PASSWORD_REPLICA=A1!correct-horse-battery", "API_" + "KEY_PRIMARY=A1!correct-horse-battery"):
            self.assertTrue(r.scan_for_secrets(diff_adding(".env", line)), line)
        # the quoted-assignment rule applies the same deny-list
        self.assertEqual(r.scan_for_secrets(diff_adding("c.py", "token_expiry_" + 'policy = "slidingexpirationpolicy1"')), [])

    def test_colon_assignments_in_yaml_and_json_are_scanned(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for path, line in [("config.yml", "DATABASE_" + 'PASSWORD: "' + pw + '"'), ("config.yml", "DATABASE_" + "PASSWORD: '" + pw + "'"),
                           ("config.yml", "DATABASE_" + "PASSWORD: " + pw), ("config.json", '"DATABASE_' + 'PASSWORD": "' + pw + '",'),
                           ("config.json", '  "STRIPE_' + 'SECRET_KEY":"' + pw + '"')]:
            findings = r.scan_for_secrets(diff_adding(path, line))
            self.assertEqual([(w, n) for w, _, n in findings], [(path, "Env-style credential")], (path, line))
        for path, line in [("ci.yml", "GH_" + "TOKEN: ${{ github.token }}"), ("a.ts", "const config = { API_" + "KEY: process.env.API_KEY_VALUE }"),
                           ("types.ts", "API_" + "KEY: string;"), ("ci.yml", "      API_" + "KEY: ${API_KEY}")]:
            self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))

    def test_percent_wrapped_single_quoted_values_are_literals(self):
        for line in ("API_" + "KEY='%Super" + "Secret123456%'", "API_" + 'KEY="%Super' + 'Secret123456%"',
                     "API_" + "KEY=%Super" + "Secret123456%"):
            self.assertEqual([n for _, _, n in r.scan_for_secrets(diff_adding(".env", line))], ["Env-style credential"], line)

    def test_credential_names_with_delimited_suffixes_reach_the_quote_aware_parser(self):
        pw = "A1!correct-horse-" + "battery-staple"
        for line in ("DATABASE_" + 'PASSWORD_PROD="' + pw + '"', "SECRET_" + "KEY_BASE='" + pw + "'",
                     "export STRIPE_" + "TOKEN_V2=" + pw, "DB_" + "PASSWORD_PROD=" + pw):
            self.assertEqual([n for _, _, n in r.scan_for_secrets(diff_adding(".env", line))], ["Env-style credential"], line)
        # a suffix does not make an unrelated name a credential
        for line in ("API_" + "KEY_FILE=/etc/keys/current.pem", "PASSWORD_MIN_" + "LENGTH=12", "TOKEN_EXPIRY_" + "SECONDS=3600"):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)

    def test_real_passphrases_that_look_like_identifiers_are_still_caught(self):
        for path, line in [("config.py", "api_" + 'key = "correct_horse_battery_staple"'),
                           (".env", "API_" + 'KEY="correct_horse_' + 'battery_staple"'),
                           (".env", "API_" + "KEY=correct_horse_battery_staple")]:
            self.assertTrue(r.scan_for_secrets(diff_adding(path, line)), (path, line))

    def test_quote_delimiters_and_dollar_literals(self):
        for path, line in [(".env", "DATABASE_" + "PASSWORD=\"A1!correct'horse-battery-staple\""),   # apostrophe inside "..."
                           (".env", "DATABASE_" + "PASSWORD='A1!correct\"horse-" + "battery-staple'"),     # quote inside '...'
                           (".env", "API_" + "KEY='$uperSecret" + "123456!'"),                              # $ is literal in '...'
                           ("app.js", "const API_" + "KEY = '$uperSecret" + "123456!';"),
                           (".env", "API_" + "KEY=\"pa\\\"ss-word-1234567\"")]:                    # escaped quote
            self.assertEqual([n for _, _, n in r.scan_for_secrets(diff_adding(path, line))], ["Env-style credential"], line)
        for line in ("API_" + 'KEY="$API_KEY"', "API_" + 'KEY="${API_KEY:-default_value_here}"', "API_" + 'KEY="$(vault read key)"',
                     "API_" + "KEY=$API_KEY_FROM_ENV", "API_" + 'KEY="{{ secrets.API_KEY }}"',
                     "API_" + 'KEY="${API_KEY_PREFIX}-${API_KEY_SUFFIX}"', "API_" + 'KEY="${API_KEY:-}"',
                     "API_" + 'KEY="${API_KEY:-changeme}"'):
            self.assertEqual(r.scan_for_secrets(diff_adding(".env", line)), [], line)

    def test_urls_and_paths_assigned_to_key_names_are_not_credentials(self):
        for value in ("https://example.com/keys/current.pem", "/etc/ssl/keys/current.pem", "./keys/public/current.pem",
                      "~/keys/ed25519.pub"):
            for line in ("PUBLIC_" + 'KEY="' + value + '"', "PUBLIC_" + "KEY=" + value):
                for path in ("app.js", ".env"):
                    self.assertEqual(r.scan_for_secrets(diff_adding(path, line)), [], (path, line))
        # a URL carrying user:password@ is still a credential
        line = "API_" + 'KEY="https://user:Zx9Yw8Vu7Ts6' + 'Rq5Po4Nm3@db.internal.net/path"'
        self.assertEqual([n for _, _, n in r.scan_for_secrets(diff_adding("app.js", line))], ["Env-style credential"])

    def test_wrapped_prose_after_an_assignment_name_is_not_a_secret(self):
        prose = "The deployment variable DATABASE_" + "PASSWORD=\nautomatically populated before startup."
        self.assertEqual(r.scan_for_secrets(DIFF, [("PR description", prose)]), [])
        # a value on the next line still counts when it is quoted or secret-shaped
        quoted = "DATABASE_" + 'PASSWORD=\n"A1!correct-horse-battery-staple"'
        self.assertEqual([n for _, _, n in r.scan_for_secrets(DIFF, [("PR description", quoted)])], ["Env-style credential"])
        shaped = "DATABASE_" + "PASSWORD=\nZx9Yw8Vu7Ts6Rq5Po4Nm3Zx9"
        self.assertEqual([n for _, _, n in r.scan_for_secrets(DIFF, [("PR description", shaped)])], ["Env-style credential"])

    def test_env_assignments_are_found_mid_line_without_any_length_limit(self):
        import time as real_time
        env = fake_secret("aws_envvar_assign")  # AWS_SECRET_ACCESS_KEY=<value with a slash and a digit>
        long_dir = "/".join(["d" * 60] * 20)  # a ~1,200-character path
        self.assertGreater(len(long_dir), 1_100)
        self.assertEqual(r.secret_name(long_dir + "/" + env + "/x.py"), "Env-style credential")
        for text in ("x\r" + env, "export A=1 " + env, "VAR=1 " + env + " run", "?" + env, "path/" + env + "/f"):
            self.assertEqual(r.secret_name(text), "Env-style credential", repr(text))
        # long hostile text stays linear
        for hostile in ("a/" * 200_000, "A_KEY" * 80_000, "A_KEY=" * 60_000, "A_KEY=$" * 60_000, "K=" + "x" * 400_000,
                        "A_KEY=" + "x" * 400_000, "A_KEY=A" + "_a" * 200_000):
            start = real_time.perf_counter()
            r.secret_name(hostile)
            self.assertLess(real_time.perf_counter() - start, 2.0, hostile[:10])

    def test_a_credential_in_the_source_path_of_a_rename_or_copy_is_caught(self):
        env = fake_secret("aws_envvar_assign")
        diff = ("diff --git a/assets/" + env + "/old.py b/src/new.py\nsimilarity index 100%\n"
                "rename from assets/" + env + "/old.py\nrename to src/new.py\n")
        self.assertEqual(r.scan_for_secrets(diff), [(r.PATH_LABEL, None, "Env-style credential")])  # once, generic label
        self.assertNotIn(env, r.secret_notice(r.scan_for_secrets(diff)))
        copy = ("diff --git a/assets/" + env + "/old.py b/src/copy.py\nsimilarity index 100%\n"
                "copy from assets/" + env + "/old.py\ncopy to src/copy.py\n")
        self.assertEqual(r.scan_for_secrets(copy), [(r.PATH_LABEL, None, "Env-style credential")])

    def test_env_lookalikes_in_ordinary_code_are_not_flagged(self):
        added = ["const API_KEY = process.env.REACT_APP_API_KEY;", "API_KEY = REACT_APP_API_KEY_FROM_ENV",
                 "const API_KEY = REACT_APP_API_KEY_V2_PRODUCTION;", "DB_PASSWORD = config.db_password_v2.value",
                 "SECRET_KEY = settings.get_secret_key_value()", "TOKEN_URL=https://example.com/oauth/token-endpoint-1",
                 'API_KEY = os.environ["API_KEY"]', "export PATH=/usr/local/bin:/usr/bin:/bin:$PATH",
                 "MAX_TOKEN = 100", "DEFAULT_PASSWORD = CHANGE_ME_IN_PRODUCTION_PLEASE"]
        self.assertEqual(r.scan_for_secrets(diff_adding("a.js", *added)), [])

    def test_pgp_armored_private_keys_are_caught_by_header_and_by_filename(self):
        header = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"
        self.assertEqual(r.scan_for_secrets(diff_adding("keys/me.txt", header)),
                         [("keys/me.txt", 2, "Private key block")])
        body_line = "A1b2C3d4" * 8  # an armor body line, with no header in the hunk's context
        self.assertEqual(r.scan_for_secrets(diff_adding("keys/me.asc", body_line)),
                         [("keys/me.asc", 2, "Key material in a key file")])

    def test_a_quoted_assignment_split_across_two_lines_is_caught(self):
        name_line, value_line = '"api_' + 'key":', '  "' + "Zx9Yw8Vu7Ts6Rq5Po4Nm3" + '"'
        self.assertEqual(r.scan_for_secrets(diff_adding("c.json", name_line, value_line)),
                         [("c.json", 3, "Hardcoded credential")])  # reported on the line holding the value
        yaml_name, yaml_value = "database_" + "password:", "  '" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Zx9" + "'"
        self.assertEqual(r.scan_for_secrets(diff_adding("c.yml", yaml_name, yaml_value)),
                         [("c.yml", 3, "Hardcoded credential")])
        # a removed name line followed by an added value line is also joined (diff order), and the pair is not
        # reported twice when a single line already matched
        self.assertEqual(len(r.scan_for_secrets(diff_adding("c.py", fake_secret("assign")))), 1)

    def test_split_lines_do_not_flag_ordinary_text(self):
        for first, second in [('"description":', '  "a long sentence with spaces in it, not a credential"'),
                              ('"token":', '  "short"'), ("api_" + "key:", "  null"),
                              ("password:", "  required_field_name_that_is_long_enough")]:
            self.assertEqual(r.scan_for_secrets(diff_adding("c.json", first, second)), [], (first, second))

    def test_each_branch_name_is_scanned_on_its_own(self):
        # the env pattern is anchored: appended to the base branch name it would never match
        rc, calls, kw = run_with_fakes("/review model=haiku", changed_files=1, head_ref=fake_secret("env"))
        self.assertEqual((rc, kw), (1, []))
        self.assertIn("branch name", last_write(calls)[0])

    def test_a_path_holding_a_credential_is_never_echoed_by_any_finding(self):
        path = "src/" + fake_secret("github") + ".txt"
        findings = r.scan_for_secrets(diff_adding(path, "x = 1", fake_secret("aws")))
        self.assertTrue(findings)
        self.assertTrue(all(where == r.PATH_LABEL for where, _, _ in findings), findings)
        self.assertNotIn(fake_secret("github"), r.secret_notice(findings))
        removed = ("diff --git a/" + path + " b/" + path + "\n--- a/" + path + "\n+++ b/" + path +
                   "\n@@ -1,1 +1,1 @@\n-" + fake_secret("aws") + "\n+fine\n")
        self.assertNotIn(fake_secret("github"), r.secret_notice(r.scan_for_secrets(removed)))

    def test_git_quoted_paths_are_unquoted_so_key_files_and_exclusions_are_recognised(self):
        quoted = 'diff --git "a/cl\\303\\251/server.pem" "b/cl\\303\\251/server.pem"\n--- "a/x"\n+++ "b/x"\n'
        self.assertEqual(r.diff_git_path(quoted.splitlines()[0]), "cl\u00e9/server.pem")
        self.assertEqual(r.diff_git_path('diff --git "a/my \\"q\\" file\\t.txt" "b/my \\"q\\" file\\t.txt"'),
                         'my "q" file\t.txt')
        self.assertEqual(r.diff_git_path("diff --git a/plain dir/file.py b/plain dir/file.py"), "plain dir/file.py")
        body = "A1b2C3d4" * 8
        diff = quoted + "@@ -1,1 +1,2 @@\n ctx\n+" + body + "\n"
        self.assertEqual(r.scan_for_secrets(diff), [("cl\u00e9/server.pem", 2, "Key material in a key file")])
        png = 'diff --git "a/caf\\303\\251.png" "b/caf\\303\\251.png"\n@@ -1 +1 @@\n+binary\n'
        self.assertTrue(r.is_excluded(r.split_diff(png)[0][0]))

    def test_a_secret_in_a_file_path_is_not_echoed_back_in_the_notice(self):
        path = "config/" + fake_secret("github") + ".json"
        findings = r.scan_for_secrets(diff_adding(path, "ok"))
        self.assertEqual(findings, [("a file path or header line in the diff", None, "GitHub token")])
        self.assertNotIn(fake_secret("github"), r.secret_notice(findings))

    def test_scan_off_is_visible_in_the_review_footer(self):
        _, calls, _ = run_with_fakes("/review model=haiku scan=off", changed_files=1)
        self.assertIn("scan off", last_write(calls)[0])
        _, calls, _ = run_with_fakes("/review model=haiku", changed_files=1)
        self.assertNotIn("scan off", last_write(calls)[0])

    def test_ordinary_code_and_workflow_syntax_is_not_flagged(self):
        added = ["GH_TOKEN: ${{ github.token }}", "TOKEN_URL=https://example.com/oauth/token-endpoint-long",
                 'password = get_user_password_from_environment_variables()', "API_KEY = os.environ[\"API_KEY\"]",
                 "secretary = 'abcdefghijklmnopqrstuvwxyz'", "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}"]
        self.assertEqual(r.scan_for_secrets(diff_adding("a.yml", *added)), [])

    def test_the_scanners_own_files_do_not_trip_it(self):
        here = Path(__file__).resolve().parent
        for name in ("review.py", "test_review.py", "config.json"):
            added = r.diff_lines((here / name).read_text(encoding="utf-8"))
            self.assertEqual(r.scan_for_secrets(diff_adding(name, *added)), [], name)

    def test_hostile_path_cannot_break_out_of_the_code_span(self):
        notice = r.secret_notice([("a`@someone [x](http://evil).py", 3, "GitHub token"), ("b\nc.py", None, "AWS access key ID")])
        self.assertNotIn("a`@someone", notice)
        self.assertIn("`a'@someone [x](http://evil).py:3`", notice)
        self.assertIn("`b'c.py`", notice)

    def test_secret_blocks_the_review_before_any_api_call(self):
        diff = diff_adding("src/app.py", "x = 1", fake_secret("anthropic"))
        rc, calls, kw = run_with_fakes("/review model=opus", changed_files=1, diff=diff, comments_page=[
            {"id": 7, "node_id": "IC_7", "user": BOT, "body": "<!-- claude-review:opus:general -->\nold good review"}])
        body, args = last_write(calls)
        self.assertEqual(rc, 1)
        self.assertEqual(kw, [])  # nothing sent to the API
        self.assertEqual(args[2], "POST")  # a new notice beside the last good review, never an edit of it
        self.assertTrue(body.startswith(r.SCAN_MARKER))  # its own marker, so it can never collapse a review
        self.assertIn("Review not sent", body)
        self.assertIn("src/app.py:3", body)
        self.assertIn("scan=off", body)
        self.assertNotIn(fake_secret("anthropic"), body)
        self.assertEqual(collapse_calls(calls), [])  # and the last good review stays visible

    def test_a_new_scan_notice_collapses_only_the_previous_scan_notice(self):
        diff = diff_adding("src/app.py", "x = 1", fake_secret("anthropic"))
        page = [
            {"id": 7, "node_id": "IC_7", "user": BOT, "body": r.SCAN_MARKER + "\nearlier notice"},
            {"id": 8, "node_id": "IC_8", "user": BOT, "body": "<!-- claude-review:opus:general -->\ngood review"},
        ]
        rc, calls, _ = run_with_fakes("/review model=opus", changed_files=1, diff=diff, comments_page=page)
        self.assertEqual(rc, 1)
        self.assertEqual([a[a.index("-f") + 1] for a in collapse_calls(calls)], ["id=IC_7"])  # the review IC_8 is untouched

    def test_a_good_review_also_clears_stale_scan_notices(self):
        page = [
            {"id": 7, "node_id": "IC_7", "user": BOT, "body": r.SCAN_MARKER + "\nstale notice"},
            {"id": 8, "node_id": "IC_8", "user": BOT, "body": MARKER + "\nearlier review"},
        ]
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=page)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(a[a.index("-f") + 1] for a in collapse_calls(calls)), ["id=IC_7", "id=IC_8"])

    def test_scan_off_sends_anyway(self):
        diff = diff_adding("src/app.py", "x = 1", fake_secret("assign"))
        rc, calls, kw = run_with_fakes("/review model=haiku scan=off", changed_files=1, diff=diff)
        self.assertEqual(rc, 0)
        self.assertEqual(len(kw), 1)

    def test_clean_diff_is_sent_and_scan_flag_is_validated(self):
        rc, _, kw = run_with_fakes("/review model=haiku", changed_files=1)
        self.assertEqual((rc, len(kw)), (0, 1))
        with self.assertRaises(r.UsageError):
            r.parse_comment("/review scan=maybe")
        self.assertTrue(r.parse_comment("/review")[0]["scan"])
        self.assertFalse(r.parse_comment("/review scan=off")[0]["scan"])

    def test_secret_in_pr_description_blocks_the_review(self):
        rc, calls, kw = run_with_fakes("/review model=haiku", changed_files=1, pr_body="token: " + fake_secret("github"))
        self.assertEqual((rc, kw), (1, []))
        self.assertIn("PR description", last_write(calls)[0])


class DiffTests(unittest.TestCase):
    def test_numbering_and_exclusion(self):
        kept, skipped = r.build_diff(DIFF + LOCK)
        self.assertEqual(skipped, ["package-lock.json"])
        self.assertIn("L2| +TWO", kept)
        self.assertIn("L4|  three", kept)
        self.assertNotIn("package-lock", kept)

    def test_split_counts_files(self):
        self.assertEqual(len(r.split_diff(DIFF + LOCK)), 2)


class FakeStream:
    request_id = "req_test123"

    def __init__(self, input_tokens, output_tokens, stop_reason="end_turn", text="**Verdict:** fine"):
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
        self.stop_reason, self.text = stop_reason, text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        blocks = [types.SimpleNamespace(type="text", text=self.text)] if self.text else []
        usage = types.SimpleNamespace(input_tokens=self.input_tokens, output_tokens=self.output_tokens)
        # no _request_id attribute, like the real ParsedMessage
        return types.SimpleNamespace(content=blocks, stop_reason=self.stop_reason, usage=usage)


def run_with_fakes(comment, changed_files, input_tokens=1000, output_tokens=1000, comments_page=None,
                   stop_reason="end_turn", text="**Verdict:** fine", attempts=None, reject_task_budget=False,
                   minimize_fails=False, minimized_ids=(), list_fails=False, diff=None, pr_title="t", pr_body="b",
                   head_ref="f", base_ref="main"):
    """Run run_review with fake gh/client. Returns (return_code, gh_calls, request_kwargs).

    `attempts` scripts successive API responses as dicts (stop_reason, text, output_tokens);
    each request's kwargs are recorded with "_beta" saying which endpoint was used.
    """
    calls, stream_kwargs = [], []
    script = list(attempts or [{"stop_reason": stop_reason, "text": text, "output_tokens": output_tokens}])

    def fake_gh(*a, payload=None, check=True):  # noqa: ARG001
        calls.append((a, payload))
        if a[:2] == ("api", "graphql"):
            if any("nodes(ids" in part for part in a):  # the visibility query
                ids = [part[len("ids[]="):] for part in a if part.startswith("ids[]=")]
                return json.dumps({"data": {"nodes": [{"id": i, "isMinimized": i in minimized_ids} for i in ids]}})
            if minimize_fails:
                raise (minimize_fails if isinstance(minimize_fails, BaseException)
                       else RuntimeError("gh api graphql failed: Resource not accessible by integration"))
            return ""
        if a[:2] == ("pr", "view"):
            return json.dumps({"title": pr_title, "body": pr_body, "baseRefName": base_ref, "headRefName": head_ref,
                               "additions": 1, "deletions": 1, "changedFiles": changed_files})
        if a[:2] == ("pr", "diff"):
            return diff if diff is not None else DIFF
        if a[0] == "api" and "--slurp" in a:
            if list_fails:
                raise RuntimeError("gh api failed: HTTP 502")
            return json.dumps([comments_page or []])
        return ""

    def make_stream(beta):
        def stream(**kw):
            stream_kwargs.append({**kw, "_beta": beta})  # checked in the test body: an assert here could be swallowed
            if beta and reject_task_budget:
                body = {"error": {"message": "task_budget is not supported for this model"}}
                raise r.anthropic.BadRequestError(  # the real SDK puts the response body into .message
                    f"Error code: 400 - {body}",
                    response=types.SimpleNamespace(request=None, status_code=400, headers={}), body=body)
            a = script.pop(0) if len(script) > 1 else script[0]
            return FakeStream(input_tokens, a["output_tokens"], a["stop_reason"], a["text"])
        return stream

    class FakeClient:
        class messages:
            stream = staticmethod(make_stream(False))

        class beta:
            class messages:
                stream = staticmethod(make_stream(True))

    old_gh, old_client = r.gh, r.anthropic.Anthropic
    r.gh, r.anthropic.Anthropic = fake_gh, lambda: FakeClient
    try:
        rc = r.run_review(types.SimpleNamespace(repo="o/r", pr="68", comment=comment, no_post=False, dry_run=False))
    finally:
        r.gh, r.anthropic.Anthropic = old_gh, old_client
    return rc, calls, stream_kwargs


def collapse_calls(calls):
    return [c[0] for c in calls if c[0][:2] == ("api", "graphql") and any("minimizeComment" in x for x in c[0])]


def last_write(calls):
    writes = [c for c in calls if c[0][:2] == ("api", "-X") and c[0][2] in ("POST", "PATCH") and c[1]]
    return writes[-1][1]["body"], writes[-1][0]


class RunTests(unittest.TestCase):
    def test_success_path_request_and_footer(self):
        rc, calls, kw = run_with_fakes("/review model=haiku effort=low", changed_files=1, input_tokens=50000, output_tokens=0)
        body, _ = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertEqual(kw[0]["thinking"], {"type": "adaptive"})
        self.assertEqual(kw[0]["output_config"], {"effort": "low", "task_budget": {"type": "tokens", "total": 20000}})
        self.assertTrue(kw[0]["_beta"])
        self.assertEqual(kw[0]["betas"], [r.TASK_BUDGET_BETA])
        self.assertEqual(kw[0]["max_tokens"], r.CONFIG["effort_budgets"]["low"]["max_tokens"])
        self.assertEqual(kw[0]["model"], r.CONFIG["models"]["haiku"]["id"])
        self.assertIn("req_test123", body)
        self.assertIn("~$0.005", body)  # short tier: 50k * $0.10/Mtok, no output tokens
        self.assertNotIn("were available", body)

    def test_haiku_long_prompt_tier(self):
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, input_tokens=150000, output_tokens=0)
        body, _ = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertIn("~$0.075", body)  # long tier: 150k * $0.50/Mtok (short tier would be $0.015)

    def test_empty_max_tokens_retries_one_effort_lower_and_sums_cost(self):
        attempts = [{"stop_reason": "max_tokens", "text": "", "output_tokens": 100000},
                    {"stop_reason": "end_turn", "text": "**Verdict:** fine", "output_tokens": 10000}]
        rc, calls, kw = run_with_fakes("/review model=opus effort=max", changed_files=1, input_tokens=10000,
                                       attempts=attempts)
        body, _ = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertEqual([k["output_config"]["effort"] for k in kw], ["max", "xhigh"])
        self.assertEqual(kw[1]["max_tokens"], r.CONFIG["effort_budgets"]["xhigh"]["max_tokens"])
        self.assertIn("automatic retry at `xhigh`", body)
        self.assertIn("**Verdict:** fine", body)
        self.assertIn("effort `xhigh`", body)
        self.assertIn("20,000 in / 110,000 out", body)
        self.assertIn("~$2.28", body)  # $4/Mtok in, $20/Mtok out: (10k in + 100k out) + (10k in + 10k out)

    def test_successful_retry_note_claims_a_review(self):
        attempts = [{"stop_reason": "max_tokens", "text": "", "output_tokens": 100000},
                    {"stop_reason": "end_turn", "text": "**Verdict:** fine", "output_tokens": 1000}]
        _, calls, _ = run_with_fakes("/review model=opus effort=max", changed_files=1, attempts=attempts)
        body, _ = last_write(calls)
        self.assertIn("this review is from an automatic retry at `xhigh`", body)
        self.assertNotIn("did not produce a review", body)

    def test_retry_that_returns_nothing_does_not_claim_a_review(self):
        attempts = [{"stop_reason": "max_tokens", "text": "", "output_tokens": 100000},
                    {"stop_reason": "end_turn", "text": "", "output_tokens": 10}]
        _, calls, _ = run_with_fakes("/review model=opus effort=max", changed_files=1, attempts=attempts)
        body, _ = last_write(calls)
        self.assertNotIn("this review is from an automatic retry", body)
        self.assertIn("did not produce a review either", body)

    def test_retry_cut_off_partway_says_so(self):
        attempts = [{"stop_reason": "max_tokens", "text": "", "output_tokens": 100000},
                    {"stop_reason": "max_tokens", "text": "**Verdict:** partial", "output_tokens": 90000}]
        _, calls, _ = run_with_fakes("/review model=opus effort=max", changed_files=1, attempts=attempts)
        body, _ = last_write(calls)
        self.assertIn("was cut off partway", body)
        self.assertIn("**Verdict:** partial", body)
        self.assertNotIn("**No review was written", body)

    def test_retry_refused_by_the_model_says_declined(self):
        class RefusedStream(FakeStream):
            def get_final_message(self):
                m = super().get_final_message()
                m.stop_reason = "refusal"
                m.stop_details = types.SimpleNamespace(category="cyber")
                return m

        first = {"stop_stream": FakeStream(1000, 100000, "max_tokens", "")}
        streams = [first["stop_stream"], RefusedStream(1000, 5, "refusal", "")]

        def scripted(client, opts, effort, system, user):
            return streams.pop(0).get_final_message(), "req_x"

        with mock.patch.object(r, "call_model", scripted):
            _, calls, _ = run_with_fakes("/review model=opus effort=max", changed_files=1)
        body, _ = last_write(calls)
        self.assertIn("was declined by the model", body)
        self.assertNotIn("did not produce a review either", body)

    def test_explicit_max_tokens_is_never_retried(self):
        dry = {"stop_reason": "max_tokens", "text": "", "output_tokens": 30000}
        _, calls, kw = run_with_fakes("/review model=opus effort=max max_tokens=30000", changed_files=1, attempts=[dry])
        body, _ = last_write(calls)
        self.assertEqual(len(kw), 1)
        self.assertIn("No review was written", body)
        self.assertNotIn("automatic retry", body)

    def test_timeout_during_retry_reports_the_first_attempts_cost(self):
        calls_made = []

        def flaky(client, opts, effort, system, user):
            calls_made.append(effort)
            if len(calls_made) == 1:
                usage = types.SimpleNamespace(input_tokens=10000, output_tokens=100000)
                return types.SimpleNamespace(content=[], stop_reason="max_tokens", usage=usage), "req_1"
            raise r.ReviewTimeout()

        with mock.patch.object(r, "call_model", flaky):
            rc, calls, _ = run_with_fakes("/review model=opus effort=max", changed_files=1)
        body, _ = last_write(calls)
        self.assertEqual(rc, 1)
        self.assertEqual(calls_made, ["max", "xhigh"])
        self.assertIn("~$2.040", body)  # first attempt: 10k * $4 + 100k * $20 per Mtok

    def test_fallback_covers_retired_beta_header_wording(self):
        for wording in ("anthropic-beta header value 'task-budgets-2026-03-13' is not recognized",
                        "unknown beta: task-budgets-2026-03-13", "task_budget is not supported"):
            body = {"error": {"message": wording}}

            def stream(**kw):
                if kw.get("betas"):
                    raise r.anthropic.BadRequestError(
                        f"Error code: 400 - {body}",
                        response=types.SimpleNamespace(request=None, status_code=400, headers={}), body=body)
                return FakeStream(1000, 1000)

            client = types.SimpleNamespace(
                beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream)),
                messages=types.SimpleNamespace(stream=stream))
            opts, _ = r.parse_comment("/review model=sonnet effort=high")
            msg, rid = r.call_model(client, opts, "high", "sys", "user")
            self.assertEqual(msg.stop_reason, "end_turn", wording)

    def test_only_task_budget_400s_trigger_the_fallback(self):
        err = r.anthropic.BadRequestError(
            "Error code: 400 - {'error': {'message': 'thinking max_tokens exceeds the model limit'}}",
            response=types.SimpleNamespace(request=None, status_code=400, headers={}), body={})

        class Client:
            class beta:
                class messages:
                    @staticmethod
                    def stream(**kw):
                        raise err

        opts, _ = r.parse_comment("/review model=sonnet effort=high")
        with self.assertRaises(r.anthropic.BadRequestError):
            r.call_model(Client, opts, "high", "sys", "user")

    def test_retry_that_also_runs_dry_reports_no_review(self):
        dry = {"stop_reason": "max_tokens", "text": "", "output_tokens": 50000}
        rc, calls, kw = run_with_fakes("/review model=opus effort=high", changed_files=1, attempts=[dry, dry])
        body, _ = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertEqual(len(kw), 2)  # exactly one retry, never a loop
        self.assertIn("No review was written", body)
        self.assertIn("did not produce a review either", body)
        self.assertNotIn("this review is from an automatic retry", body)

    def test_lowest_effort_is_not_retried(self):
        dry = {"stop_reason": "max_tokens", "text": "", "output_tokens": 50000}
        _, calls, kw = run_with_fakes("/review model=haiku effort=low", changed_files=1, attempts=[dry])
        self.assertEqual(len(kw), 1)

    def test_partial_text_at_max_tokens_is_kept_without_retry(self):
        part = {"stop_reason": "max_tokens", "text": "**Verdict:** partial", "output_tokens": 40000}
        _, calls, kw = run_with_fakes("/review model=sonnet effort=high", changed_files=1, attempts=[part])
        body, _ = last_write(calls)
        self.assertEqual(len(kw), 1)
        self.assertIn("**Verdict:** partial", body)
        self.assertIn("Output hit `max_tokens=", body)

    def test_task_budget_rejection_falls_back_without_it(self):
        rc, calls, kw = run_with_fakes("/review model=sonnet effort=high", changed_files=1, reject_task_budget=True)
        body, _ = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertTrue(kw[0]["_beta"])
        self.assertFalse(kw[1]["_beta"])
        self.assertEqual(kw[1]["output_config"], {"effort": "high"})
        self.assertIn("**Verdict:** fine", body)

    def test_timeout_posts_a_failure_comment_instead_of_dying_silently(self):
        with mock.patch.object(r, "call_model", side_effect=r.ReviewTimeout()):
            rc, calls, _ = run_with_fakes("/review model=opus effort=max", changed_files=1)
        body, _ = last_write(calls)
        self.assertEqual(rc, 1)
        self.assertIn(f"timed out after {r.CONFIG['limits']['deadline_seconds'] // 60} minutes", body)
        self.assertNotIn("$0.000", body)  # no attempt completed, so no cost sentence
        self.assertNotIn("attempt(s) that completed", body)

    def test_review_timeout_is_not_swallowed_by_except_exception(self):
        self.assertFalse(issubclass(r.ReviewTimeout, Exception))  # the SDK retry loop catches Exception

    def test_no_retry_when_too_little_time_is_left(self):
        dry = {"stop_reason": "max_tokens", "text": "", "output_tokens": 50000}
        deadline = r.CONFIG["limits"]["deadline_seconds"]
        readings = [0.0]  # first reading = start; every later reading = 60s before the deadline

        def clock():
            return readings.pop(0) if readings else deadline - 60.0

        with mock.patch.object(r, "time", types.SimpleNamespace(monotonic=clock)):
            rc, calls, kw = run_with_fakes("/review model=opus effort=max", changed_files=1, attempts=[dry])
        body, _ = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertEqual(len(kw), 1)
        self.assertIn("No review was written", body)

    def test_incomplete_diff_warning(self):
        rc, calls, _ = run_with_fakes("/review", changed_files=3)
        body, _ = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertIn("Only 1 of 3 changed files", body)

    def _page(self):
        return [
            {"id": 5, "node_id": "IC_5", "user": None, "body": MARKER + "\nghost"},
            {"id": 6, "node_id": "IC_6", "user": BOT, "body": None},
            {"id": 7, "node_id": "IC_7", "user": BOT, "body": MARKER + "\nold"},
            {"id": 8, "node_id": "IC_8", "user": {"type": "User", "login": "someone"}, "body": MARKER + "\nspoof"},
            {"id": 9, "node_id": "IC_9", "user": {"type": "Bot", "login": "other-app[bot]"}, "body": MARKER + "\nother app"},
        ]

    def test_posts_a_new_comment_and_collapses_only_its_own_earlier_one(self):
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=self._page())
        self.assertEqual(rc, 0)
        _, args = last_write(calls)
        self.assertEqual(args[2], "POST")  # a new comment, not a PATCH of the old one: edits don't wake the PR monitor
        self.assertTrue(args[3].endswith("/issues/68/comments"))
        collapsed = collapse_calls(calls)
        self.assertEqual([a[a.index("-f") + 1] for a in collapsed], ["id=IC_7"])  # not the spoofed/other-app/null ones
        self.assertTrue(any("classifier: OUTDATED" in part for part in collapsed[0]))
        self.assertFalse(any(c[0][:3] == ("api", "-X", "PATCH") for c in calls))

    def test_failures_never_collapse_the_last_good_review(self):
        with mock.patch.object(r, "call_model", side_effect=r.ReviewTimeout()):
            rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=self._page())
        self.assertEqual(rc, 1)
        self.assertIn("Review failed", last_write(calls)[0])
        self.assertFalse(any(c[0][:2] == ("api", "graphql") for c in calls))
        # a usage error also never touches reviews (its own marker only matches earlier usage notices)
        rc, calls, _ = run_with_fakes("/review model=nope", changed_files=1, comments_page=self._page())
        self.assertEqual(rc, 1)
        self.assertEqual(collapse_calls(calls), [])

    def test_any_collapse_error_is_swallowed(self):
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=self._page(),
                                      minimize_fails=OSError("gh not runnable"))
        self.assertEqual(rc, 0)
        self.assertIn("**Verdict:** fine", last_write(calls)[0])

    def test_listing_failure_still_posts_the_review(self):
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, list_fails=True)
        body, args = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertEqual(args[2], "POST")
        self.assertIn("**Verdict:** fine", body)
        self.assertEqual(collapse_calls(calls), [])

    def test_already_minimized_comments_are_not_touched_again(self):
        page = [
            {"id": 7, "node_id": "IC_7", "user": BOT, "body": MARKER + "\nold"},
            {"id": 8, "node_id": "IC_8", "user": BOT, "body": MARKER + "\nolder, already collapsed"},
            {"id": 9, "node_id": "IC_9", "user": BOT, "body": MARKER + "\nnewest visible"},
        ]
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=page,
                                      minimized_ids={"IC_7", "IC_8"})
        self.assertEqual(rc, 0)
        self.assertEqual([a[a.index("-f") + 1] for a in collapse_calls(calls)], ["id=IC_9"])

    def test_collapsing_stops_after_the_first_failure(self):
        page = [{"id": i, "node_id": f"IC_{i}", "user": BOT, "body": MARKER + "\nold"} for i in (7, 8, 9)]
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=page,
                                      minimize_fails=True)
        self.assertEqual(rc, 0)
        self.assertEqual(len(collapse_calls(calls)), 1)  # not one warning per old comment

    def test_repeated_usage_errors_leave_one_visible_notice(self):
        usage_marker = "<!-- claude-review:usage -->"
        page = [
            {"id": 7, "node_id": "IC_7", "user": BOT, "body": usage_marker + "\nUsage..."},
            {"id": 8, "node_id": "IC_8", "user": BOT, "body": MARKER + "\na good review"},
        ]
        rc, calls, _ = run_with_fakes("/review model=nope", changed_files=1, comments_page=page)
        self.assertEqual(rc, 1)
        self.assertEqual([a[a.index("-f") + 1] for a in collapse_calls(calls)], ["id=IC_7"])  # the review IC_8 is untouched

    def test_old_visible_reviews_are_not_starved_by_a_long_collapsed_run(self):
        # 150 earlier reviews: the newest 120 are already collapsed, the oldest 30 are still visible
        page = [{"id": i, "node_id": f"IC_{i}", "user": BOT, "body": MARKER + "\nold"} for i in range(1, 151)]
        collapsed = {f"IC_{i}" for i in range(31, 151)}
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=page,
                                      minimized_ids=collapsed)
        self.assertEqual(rc, 0)
        done = [a[a.index("-f") + 1] for a in collapse_calls(calls)]
        self.assertEqual(len(done), r.MAX_COLLAPSE)
        self.assertEqual(done, [f"id=IC_{i}" for i in range(30, 10, -1)])  # visible ones found past the first chunk, newest first
        self.assertEqual(sum(1 for c in calls if c[0][:2] == ("api", "graphql") and any("nodes(ids" in x for x in c[0])), 2)

    def test_only_the_newest_earlier_reviews_are_considered(self):
        page = [{"id": i, "node_id": f"IC_{i}", "user": BOT, "body": MARKER + "\nold"} for i in range(1, 41)]
        _, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=page)
        done = [a[a.index("-f") + 1] for a in collapse_calls(calls)]
        self.assertEqual(done, [f"id=IC_{i}" for i in range(40, 20, -1)])  # the newest 20, newest first

    def test_first_review_has_nothing_to_collapse(self):
        _, calls, _ = run_with_fakes("/review model=haiku", changed_files=1)
        self.assertFalse(any(c[0][:2] == ("api", "graphql") for c in calls))

    def test_collapse_failure_does_not_fail_the_review(self):
        rc, calls, _ = run_with_fakes("/review model=haiku", changed_files=1, comments_page=self._page(),
                                      minimize_fails=True)
        body, args = last_write(calls)
        self.assertEqual(rc, 0)
        self.assertEqual(args[2], "POST")
        self.assertIn("**Verdict:** fine", body)


if __name__ == "__main__":
    unittest.main()
