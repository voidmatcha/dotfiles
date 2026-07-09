from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "analyze_session_feedback_jsonl.py"
SPEC = importlib.util.spec_from_file_location("session_feedback_audit", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SessionFeedbackAuditTest(unittest.TestCase):
    def write_jsonl(self, path: Path, rows: list[object]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def run_cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_detects_english_feedback_patterns(self) -> None:
        text = "No, that is not what I meant. Stop asking whether to proceed; just run it and verify the result."

        categories = MODULE.categorize(text)

        self.assertIn("scope_correction", categories)
        self.assertIn("direct_action", categories)
        self.assertIn("avoid_confirmation", categories)

    def test_keeps_korean_feedback_detection_in_the_builtin_pattern_pack(self) -> None:
        text = "아니, 그게 아니라 확인 질문하지 말고 바로 실행하고 검증해줘"

        categories = MODULE.categorize(text)
        packs = MODULE.matching_builtin_packs(text)

        self.assertIn("scope_correction", categories)
        self.assertIn("direct_action", categories)
        self.assertIn("avoid_confirmation", categories)
        self.assertEqual(packs, ["ko"])

    def test_latin_script_is_not_claimed_as_english(self) -> None:
        text = "Bonjour, veuillez continuer sans demander de confirmation."

        self.assertEqual(MODULE.matching_builtin_packs(text), [])

    def test_mixed_message_does_not_force_korean_rule_output(self) -> None:
        rows = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "Please polish the 한국어 copy and do it now.",
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "Please polish the 한국어 copy and do it now.",
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1)

        self.assertEqual(result["matched_builtin_packs"], {"ko": 2, "en": 2})
        self.assertEqual(result["output_language"], "en")
        self.assertEqual(result["rules"], [])

    def test_auto_output_language_does_not_infer_language_from_phrase_pack_hits(self) -> None:
        row = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Please review and check the 한국어 content carefully.",
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.jsonl"
            second = Path(temp_dir) / "second.jsonl"
            self.write_jsonl(first, [row])
            self.write_jsonl(second, [row])
            result = MODULE.analyze([first, second], limit_files=2)

        self.assertEqual(result["matched_builtin_packs"], {"ko": 2})
        self.assertEqual(result["repeated_patterns"], {"language_polish": 2})
        self.assertEqual(result["output_language"], "en")
        self.assertEqual(
            result["rules"],
            [MODULE.RULE_TEMPLATES["en"]["language_polish"]],
        )

    def test_explicit_korean_output_language_is_honored(self) -> None:
        row = {
            "type": "user",
            "message": {"role": "user", "content": "한국어 문구를 윤문해줘"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.jsonl"
            second = Path(temp_dir) / "second.jsonl"
            self.write_jsonl(first, [row])
            self.write_jsonl(second, [row])
            result = MODULE.analyze(
                [first, second],
                limit_files=2,
                output_language="ko",
            )

        self.assertEqual(result["output_language"], "ko")
        self.assertTrue(result["rules"])
        self.assertTrue(all(rule in MODULE.RULE_TEMPLATES["ko"].values() for rule in result["rules"]))

    def test_accepts_a_custom_pattern_pack_for_another_language(self) -> None:
        patterns = {"scope_correction": ["そうではなく"]}

        categories = MODULE.categorize("そうではなく、別の画面を修正してください", patterns)

        self.assertIn("scope_correction", categories)

    def test_extracts_keywords_from_non_latin_custom_pattern_text(self) -> None:
        patterns = {"scope_correction": ["そうではなく"]}
        rows = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "そうではなく、設定画面を修正してください",
                },
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1, extra_patterns=patterns)

        self.assertTrue(any("設定画面" in keyword for keyword in result["keywords"]))

    def test_plain_english_no_is_not_a_scope_correction(self) -> None:
        categories = MODULE.categorize("There are no errors in the final report.")

        self.assertNotIn("scope_correction", categories)

    def test_runtime_patterns_use_generic_environment_terms(self) -> None:
        generic = MODULE.categorize("Verify this in the staging environment and container.")
        frontend_specific = MODULE.categorize("Check the WebView on iPhone.")

        self.assertIn("runtime_environment", generic)
        self.assertNotIn("runtime_environment", frontend_specific)

    def test_korean_repo_boundary_uses_general_repository_terms(self) -> None:
        categories = MODULE.categorize("다른 저장소 변경과 섞지 말고 작업 디렉터리를 확인해줘")

        self.assertIn("repo_boundary", categories)

    def test_extracts_real_claude_and_existing_codex_user_shapes(self) -> None:
        rows = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Run it and verify it."}],
                },
            },
            {
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Please execute it now."}],
                }
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1)

        self.assertEqual(result["stats"]["user_messages"], 2)
        self.assertEqual(result["categories"]["direct_action"], 2)

    def test_redacts_secrets_cookies_query_tokens_and_emails_before_derivation(self) -> None:
        password_key = "pass" + "word"
        secrets = [
            "private-bearer-value",
            "private-json-value",
            "private-assignment-value",
            "private-cookie-value",
            "private-query-value",
            "person.private@example.com",
        ]
        text = "\n".join(
            [
                "Run it and verify it.",
                "Authorization: Bearer private-bearer-value",
                '{"api_key": "private-json-value"}',
                f"{password_key}=private-assignment-value",
                "Cookie: sessionid=private-cookie-value",
                "https://example.test/callback?access_token=private-query-value&mode=check",
                "Contact person.private@example.com",
            ]
        )
        rows = [
            {
                "type": "user",
                "message": {"role": "user", "content": text},
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "person.private@example.com-session.jsonl"
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1)
            serialized = json.dumps(result, ensure_ascii=False)
            markdown = MODULE.render_markdown(result)

        for secret in secrets:
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret, markdown)
        self.assertIn("<redacted", serialized)
        self.assertFalse(any("private" in keyword.lower() for keyword in result["keywords"]))

    def test_redacts_standalone_provider_tokens_before_all_derivation(self) -> None:
        provider_tokens = [
            "".join(("s", "k", "-", "A" * 24)),
            "".join(("s", "k", "-", "proj", "-", "B" * 32)),
            "".join(("g", "h", "p", "_", "C" * 36)),
            "".join(("github", "_", "pat", "_", "D" * 30)),
            ".".join(("ey" + "J" + "E" * 12, "ey" + "J" + "F" * 16, "G" * 32)),
        ]
        text = "Run it and verify these bare credentials: " + " ".join(provider_tokens)
        rows = [{"type": "user", "message": {"role": "user", "content": text}}]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / (provider_tokens[0] + "-session.jsonl")
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1)
            serialized = json.dumps(result, ensure_ascii=False)
            markdown = MODULE.render_markdown(result)

        for token in provider_tokens:
            self.assertNotIn(token, serialized)
            self.assertNotIn(token, markdown)
        self.assertGreaterEqual(serialized.count("<redacted>"), len(provider_tokens))
        self.assertNotIn(provider_tokens[0], result["files"][0]["path"])

    def test_redacts_prefixed_sensitive_assignments(self) -> None:
        values = [
            "aws-private-value",
            "database-private-value",
            "openai-private-value",
            "stripe-private-value",
            "ssh-private-value",
            "secret-key-private-value",
            "postgres://user:private-password@example.test/db",
        ]
        text = "\n".join(
            [
                f"AWS_SECRET_ACCESS_KEY={values[0]}",
                f"DATABASE_PASSWORD={values[1]}",
                f'{{"OPENAI_API_KEY": "{values[2]}"}}',
                f"STRIPE_SECRET_KEY={values[3]}",
                f"SSH_PRIVATE_KEY={values[4]}",
                f"SECRET_KEY={values[5]}",
                f"DATABASE_URL={values[6]}",
            ]
        )

        redacted = MODULE.redact_sensitive(text)

        for value in values:
            self.assertNotIn(value, redacted)
        self.assertGreaterEqual(redacted.count("<redacted>"), len(values))

    def test_redacts_aws_access_key_ids_in_assignments_and_bare_text(self) -> None:
        access_key = "".join(("AK", "IA", "ABCDEFGHIJKLMNOP"))
        text = f"AWS_ACCESS_KEY_ID={access_key}\nretry with bare {access_key}"

        redacted = MODULE.redact_sensitive(text)

        self.assertNotIn(access_key, redacted)
        self.assertEqual(redacted.count("<redacted>"), 2)

    def test_redacts_private_key_blocks_before_all_derivation(self) -> None:
        delimiter = "-" * 5
        label = "PRIVATE" + " KEY"
        begin = delimiter + "BEGIN " + label + delimiter
        end = delimiter + "END " + label + delimiter
        key_body = "M" * 48 + "\n" + "N" * 48
        private_key = "\n".join((begin, key_body, end))
        text = "Run it now. The pasted credential is:\n" + private_key + "\nVerify it."
        rows = [{"type": "user", "message": {"role": "user", "content": text}}]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1)
            serialized = json.dumps(result, ensure_ascii=False)
            markdown = MODULE.render_markdown(result)

        for secret_part in (begin, end, key_body, private_key):
            self.assertNotIn(secret_part, serialized)
            self.assertNotIn(secret_part, markdown)
        self.assertIn("<redacted>", serialized)

    def test_analyze_streams_jsonl_without_read_text(self) -> None:
        rows = [
            {
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": "Run it.",
                }
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("must stream JSONL")):
                result = MODULE.analyze([path], limit_files=1)

        self.assertEqual(result["stats"]["user_messages"], 1)

    def test_same_pattern_twice_in_one_file_remains_a_candidate(self) -> None:
        rows = [
            {"type": "user", "message": {"role": "user", "content": "Run it now."}},
            {"type": "user", "message": {"role": "user", "content": "Send the report link."}},
            {"type": "user", "message": {"role": "user", "content": "The artifact path is missing."}},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1)
            markdown = MODULE.render_markdown(result)

        self.assertEqual(result["categories"]["direct_action"], 1)
        self.assertEqual(result["repeated_patterns"], {})
        self.assertEqual(result["candidate_patterns"], {"artifact_link": 2, "direct_action": 1})
        self.assertEqual(result["pattern_evidence"]["artifact_link"], {"occurrences": 2, "files": 1})
        self.assertEqual(result["rules"], [])
        self.assertIn("## Repeated patterns", markdown)
        self.assertIn("## Candidate patterns", markdown)
        self.assertIn("**artifact_link**: 2 occurrences across 1 file", markdown)
        self.assertIn("**direct_action**: 1 occurrence across 1 file", markdown)

    def test_pattern_across_two_files_generates_a_durable_rule(self) -> None:
        row = {"type": "user", "message": {"role": "user", "content": "Send the report link."}}

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.jsonl"
            second = Path(temp_dir) / "second.jsonl"
            self.write_jsonl(first, [row])
            self.write_jsonl(second, [row])
            result = MODULE.analyze([first, second], limit_files=2)

        self.assertEqual(result["repeated_patterns"], {"artifact_link": 2})
        self.assertEqual(result["pattern_evidence"]["artifact_link"], {"occurrences": 2, "files": 2})
        self.assertEqual(result["rules"], [MODULE.RULE_TEMPLATES["en"]["artifact_link"]])

    def test_cli_can_deliberately_allow_a_single_file_threshold(self) -> None:
        rows = [
            {"type": "user", "message": {"role": "user", "content": "Send the report link."}},
            {"type": "user", "message": {"role": "user", "content": "The artifact path is missing."}},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            completed = self.run_cli(str(path), "--min-files", "1", "--format", "json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["repeated_patterns"], {"artifact_link": 2})

    def test_nonpositive_evidence_threshold_exits_nonzero(self) -> None:
        completed = self.run_cli("--min-files", "0")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("greater than zero", completed.stderr.lower())

    def test_explicit_missing_input_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.jsonl"
            completed = self.run_cli(str(missing))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("missing", completed.stderr.lower())

    def test_explicit_non_jsonl_input_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.txt"
            path.write_text("{}\n", encoding="utf-8")
            completed = self.run_cli(str(path))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("jsonl", completed.stderr.lower())

    def test_explicit_directory_without_jsonl_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = self.run_cli(temp_dir)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("jsonl", completed.stderr.lower())

    def test_invalid_recent_filter_exits_nonzero_without_traceback(self) -> None:
        completed = self.run_cli("--recent", "sometime")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("duration", completed.stderr.lower())
        self.assertNotIn("traceback", completed.stderr.lower())

    def test_explicit_malformed_jsonl_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.jsonl"
            path.write_text("not-json\n", encoding="utf-8")
            completed = self.run_cli(str(path))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("valid json", completed.stderr.lower())

    def test_mixed_valid_and_invalid_jsonl_lines_remains_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mixed.jsonl"
            path.write_text(
                "not-json\n"
                + json.dumps({"type": "user", "message": {"role": "user", "content": "Run it."}})
                + "\n",
                encoding="utf-8",
            )
            completed = self.run_cli(str(path), "--format", "json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["stats"]["bad_json_lines"], 1)
        self.assertEqual(result["stats"]["user_messages"], 1)

    def test_all_unreadable_inputs_fail(self) -> None:
        stderr = io.StringIO()
        stdout = io.StringIO()
        with mock.patch.object(MODULE, "iter_paths", return_value=[Path("unreadable.jsonl")]):
            with mock.patch.object(Path, "open", side_effect=PermissionError("denied")):
                with redirect_stderr(stderr), redirect_stdout(stdout):
                    return_code = MODULE.main(["unreadable.jsonl"])

        self.assertNotEqual(return_code, 0)
        self.assertIn("unreadable", stderr.getvalue().lower())
        self.assertEqual(stdout.getvalue(), "")

    def test_output_is_atomically_replaced_with_private_permissions(self) -> None:
        rows = [{"type": "user", "message": {"role": "user", "content": "Run it."}}]

        with tempfile.TemporaryDirectory() as temp_dir:
            session = Path(temp_dir) / "session.jsonl"
            output = Path(temp_dir) / "report.json"
            self.write_jsonl(session, rows)
            output.write_text("old report", encoding="utf-8")
            output.chmod(0o644)
            real_replace = os.replace
            with mock.patch.object(MODULE.os, "replace", wraps=real_replace) as replace:
                return_code = MODULE.main(
                    [str(session), "--format", "json", "--out", str(output)]
                )
            mode = stat.S_IMODE(output.stat().st_mode)
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(return_code, 0)
        replace.assert_called_once()
        self.assertEqual(mode, 0o600)
        self.assertEqual(data["stats"]["user_messages"], 1)

    def test_no_input_is_a_successful_empty_report_when_default_store_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = dict(os.environ)
            env["HOME"] = temp_dir
            completed = self.run_cli("--format", "json", env=env)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["stats"].get("user_messages", 0), 0)

    @unittest.skipUnless(Path("/usr/bin/python3").exists(), "system Python is unavailable")
    def test_script_compiles_with_system_python_3_9(self) -> None:
        version = subprocess.run(
            ["/usr/bin/python3", "-c", "import sys; print(sys.version_info[:2])"],
            capture_output=True,
            text=True,
            check=False,
        )
        if version.stdout.strip() != "(3, 9)":
            self.skipTest("system Python is not 3.9")

        completed = subprocess.run(
            ["/usr/bin/python3", "-m", "py_compile", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_report_uses_language_neutral_labels(self) -> None:
        rows = [
            {
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "No, just run it and verify the result."}],
                }
            },
            {
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "아니, 그냥 실행하고 검증해줘"}],
                }
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            self.write_jsonl(path, rows)
            result = MODULE.analyze([path], limit_files=1)
            report = MODULE.render_markdown(result)

        self.assertIn("# Session feedback audit", report)
        self.assertIn("User messages matching built-in pattern packs: 2", report)
        self.assertIn("Matched built-in packs: en=1, ko=1", report)
        self.assertNotIn("Korean AI slop", report)


if __name__ == "__main__":
    unittest.main()
