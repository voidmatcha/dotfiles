#!/usr/bin/env python3
"""Behavioral tests for scripts/code_intel_doctor.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/code_intel_doctor.py"


class CodeIntelDoctorTest(unittest.TestCase):
    def run_doctor(
        self,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=cwd or ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def write_executable(path: Path, source: str) -> None:
        path.write_text(f"#!{sys.executable}\n{source}")
        path.chmod(0o755)

    def fixture(
        self,
        temp: Path,
        status: object,
        *,
        status_exit: int = 0,
    ) -> tuple[Path, dict[str, str]]:
        target = temp / "repo"
        target.mkdir()
        (target / ".codegraph").mkdir()
        (target / ".serena").mkdir()

        home = temp / "home"
        (home / ".codex").mkdir(parents=True)
        (home / ".codex/config.toml").write_text(
            "[mcp_servers.codegraph]\ncommand = 'codegraph'\n"
            "[mcp_servers.serena]\ncommand = 'serena'\n"
        )

        bin_dir = temp / "bin"
        bin_dir.mkdir()
        for command in ("serena", "codex", "claude"):
            self.write_executable(bin_dir / command, "raise SystemExit(0)\n")
        self.write_executable(
            bin_dir / "codegraph",
            """
import os
import sys

expected_repo = os.environ["EXPECTED_REPO"]
if sys.argv[1:] != ["status", "--json", expected_repo]:
    print(f"unexpected arguments: {sys.argv[1:]!r}", file=sys.stderr)
    raise SystemExit(64)
print(os.environ["CODEGRAPH_STATUS_JSON"])
raise SystemExit(int(os.environ.get("CODEGRAPH_STATUS_EXIT", "0")))
""".lstrip(),
        )

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "PATH": str(bin_dir),
                "EXPECTED_REPO": str(target.resolve()),
                "CODEGRAPH_STATUS_JSON": json.dumps(status),
                "CODEGRAPH_STATUS_EXIT": str(status_exit),
            }
        )
        return target, env

    def test_help_is_real_argparse_help(self) -> None:
        result = self.run_doctor("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("--json", result.stdout)
        self.assertIn("--strict", result.stdout)
        self.assertNotIn("# Code Intel Doctor", result.stdout)

    def test_rejects_missing_and_nondirectory_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            missing = temp / "missing"
            missing_result = self.run_doctor(str(missing))
            self.assertEqual(missing_result.returncode, 2)
            self.assertIn("does not exist", missing_result.stderr)

            regular_file = temp / "not-a-directory"
            regular_file.write_text("not a repository")
            file_result = self.run_doctor(str(regular_file))
            self.assertEqual(file_result.returncode, 2)
            self.assertIn("not a directory", file_result.stderr)

    def test_clean_codegraph_json_passes_strict_mode(self) -> None:
        status = {
            "pendingChanges": {"added": 0, "modified": 0, "removed": 0},
            "worktreeMismatch": None,
            "index": {"reindexRecommended": False},
        }
        with tempfile.TemporaryDirectory() as raw_temp:
            target, env = self.fixture(Path(raw_temp), status)
            result = self.run_doctor("--json", "--strict", str(target), env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["targetRepo"], str(target.resolve()))
        self.assertTrue(report["commands"]["codegraph"]["available"])
        self.assertEqual(
            report["codegraphStatus"]["reindexRecommended"], False
        )
        self.assertEqual(report["codegraphStatus"]["pendingChangeCount"], 0)
        self.assertIsNone(report["codegraphStatus"]["worktreeMismatch"])
        self.assertEqual(report["issues"], [])

    def test_stale_status_reports_all_signals_and_strict_fails(self) -> None:
        mismatch = {"indexed": "/repo-a", "current": "/repo-b"}
        status = {
            "pendingChanges": {"added": 1, "modified": 2, "removed": 3},
            "worktreeMismatch": mismatch,
            "index": {"reindexRecommended": True},
        }
        with tempfile.TemporaryDirectory() as raw_temp:
            target, env = self.fixture(Path(raw_temp), status)
            json_result = self.run_doctor(
                "--json", "--strict", str(target), env=env
            )
            text_result = self.run_doctor("--strict", str(target), env=env)

        self.assertEqual(json_result.returncode, 1, json_result.stderr)
        report = json.loads(json_result.stdout)
        self.assertFalse(report["ok"])
        self.assertTrue(report["codegraphStatus"]["reindexRecommended"])
        self.assertEqual(report["codegraphStatus"]["pendingChangeCount"], 6)
        self.assertEqual(report["codegraphStatus"]["worktreeMismatch"], mismatch)
        issue_codes = {issue["code"] for issue in report["issues"]}
        self.assertTrue(
            {
                "codegraph_reindex_recommended",
                "codegraph_pending_changes",
                "codegraph_worktree_mismatch",
            }.issubset(issue_codes)
        )

        self.assertEqual(text_result.returncode, 1, text_result.stderr)
        self.assertIn("reindexRecommended: YES", text_result.stdout)
        self.assertIn("pendingChanges: 6", text_result.stdout)
        self.assertIn("worktreeMismatch: DETECTED", text_result.stdout)

    def test_unknown_status_fields_fail_closed_in_strict_mode(self) -> None:
        status = {
            "pendingChanges": ["not", "counts"],
            "index": {"reindexRecommended": "false"},
        }
        with tempfile.TemporaryDirectory() as raw_temp:
            target, env = self.fixture(Path(raw_temp), status)
            result = self.run_doctor("--json", "--strict", str(target), env=env)

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        issue_codes = {issue["code"] for issue in report["issues"]}
        self.assertTrue(
            {
                "codegraph_reindex_unknown",
                "codegraph_pending_changes_unknown",
                "codegraph_worktree_mismatch_unknown",
            }.issubset(issue_codes)
        )

    def test_status_command_failure_is_reported_and_strict_fails(self) -> None:
        status = {"error": "index unavailable"}
        with tempfile.TemporaryDirectory() as raw_temp:
            target, env = self.fixture(Path(raw_temp), status, status_exit=7)
            result = self.run_doctor("--json", "--strict", str(target), env=env)

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["codegraphStatus"]["commandOk"])
        self.assertIn("exited 7", report["codegraphStatus"]["error"])
        self.assertIn(
            "codegraph_status_failed",
            {issue["code"] for issue in report["issues"]},
        )

    def test_non_strict_mode_reports_problems_without_failing(self) -> None:
        status = {
            "pendingChanges": {"added": 1, "modified": 0, "removed": 0},
            "worktreeMismatch": None,
            "index": {"reindexRecommended": False},
        }
        with tempfile.TemporaryDirectory() as raw_temp:
            target, env = self.fixture(Path(raw_temp), status)
            result = self.run_doctor("--json", str(target), env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertIn(
            "codegraph_pending_changes",
            {issue["code"] for issue in report["issues"]},
        )


if __name__ == "__main__":
    unittest.main()
