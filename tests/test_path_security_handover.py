#!/usr/bin/env python3
from __future__ import annotations

import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOVER = REPO_ROOT / "plugins/local-skills/skills/handover/scripts/handover.py"


class HandoverPathSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.cwd = self.root / "repo"
        self.out_root = self.root / "artifacts"
        self.cwd.mkdir()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_handover(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(HANDOVER), *args],
            text=True,
            capture_output=True,
            check=False,
            cwd=self.cwd,
        )

    def assert_mode(self, path: Path, expected: int) -> None:
        actual = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(actual, expected, f"unexpected mode for {path}: {actual:#o}")

    def init(
        self,
        *,
        run_id: str = "safe-run_1.v2",
        target: str = "custom-agent_2.v1",
        handshake: str = "fast",
    ) -> Path:
        result = self.run_handover(
            "init",
            "--cwd",
            str(self.cwd),
            "--out-root",
            str(self.out_root),
            "--run-id",
            run_id,
            "--target",
            target,
            "--handshake",
            handshake,
            "--task",
            "Continue safely",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(json.loads(result.stdout)["run_dir"])

    def test_safe_custom_target_completes_fast_handover(self) -> None:
        target = "custom-agent_2.v1"
        run_dir = self.init(target=target)

        ready = self.run_handover(
            "ready",
            "--run-dir",
            str(run_dir),
            "--target",
            target,
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        self.assertEqual(ready.returncode, 0, ready.stderr)
        report = self.run_handover("validate", "--run-dir", str(run_dir))
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertTrue(json.loads(report.stdout)["complete"])
        ready_path = run_dir / "targets" / target / "ready.json"
        self.assertTrue(ready_path.is_file())

        for private_dir in (
            run_dir,
            run_dir / "target-prompts",
            run_dir / "targets",
            run_dir / "targets" / target,
        ):
            with self.subTest(private_dir=private_dir):
                self.assert_mode(private_dir, 0o700)

        for private_file in (
            run_dir / "handoff.json",
            run_dir / "handoff.md",
            run_dir / "launch-commands.json",
            run_dir / "state.jsonl",
            run_dir / "target-prompts" / f"{target}.txt",
            ready_path,
        ):
            with self.subTest(private_file=private_file):
                self.assert_mode(private_file, 0o600)

    def test_ready_rejects_receiver_launched_from_wrong_cwd(self) -> None:
        run_dir = self.init(target="codex")
        wrong_cwd = self.root / "wrong-repo"
        wrong_cwd.mkdir()

        result = subprocess.run(
            [
                "python3",
                str(HANDOVER),
                "ready",
                "--run-dir",
                str(run_dir),
                "--target",
                "codex",
                "--summary",
                "Understood",
                "--next-action",
                "Continue",
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=wrong_cwd,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("receiver cwd mismatch", result.stderr)
        self.assertFalse((run_dir / "targets" / "codex" / "ready.json").exists())

    def test_validate_rejects_forged_ready_cwd_and_git_types(self) -> None:
        run_dir = self.init(target="codex")
        ready = self.run_handover(
            "ready",
            "--run-dir",
            str(run_dir),
            "--target",
            "codex",
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        self.assertEqual(ready.returncode, 0, ready.stderr)
        ready_path = run_dir / "targets" / "codex" / "ready.json"
        payload = json.loads(ready_path.read_text(encoding="utf-8"))
        payload["cwd"] = None
        payload["git"] = None
        ready_path.write_text(json.dumps(payload), encoding="utf-8")

        report = self.run_handover("validate", "--run-dir", str(run_dir))

        self.assertNotEqual(report.returncode, 0)
        self.assertIn("wrong cwd", report.stdout)

    def test_verified_confirmation_timestamp_is_stable_across_wait_polls(self) -> None:
        run_dir = self.init(target="codex", handshake="verified")
        ack = self.run_handover(
            "ack",
            "--run-dir",
            str(run_dir),
            "--target",
            "codex",
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        self.assertEqual(ack.returncode, 0, ack.stderr)
        confirm = self.run_handover("confirm", "--run-dir", str(run_dir))
        self.assertEqual(confirm.returncode, 0, confirm.stderr)
        confirm_path = run_dir / "source-confirmed.json"
        first_timestamp = json.loads(confirm_path.read_text(encoding="utf-8"))["confirmed_at"]

        for _ in range(2):
            wait = self.run_handover(
                "wait",
                "--run-dir",
                str(run_dir),
                "--timeout",
                "0",
                "--interval",
                "0.01",
            )
            self.assertNotEqual(wait.returncode, 0)
            current_timestamp = json.loads(confirm_path.read_text(encoding="utf-8"))["confirmed_at"]
            self.assertEqual(current_timestamp, first_timestamp)

        ready = self.run_handover(
            "ready",
            "--run-dir",
            str(run_dir),
            "--target",
            "codex",
        )
        self.assertEqual(ready.returncode, 0, ready.stderr)
        report = self.run_handover("validate", "--run-dir", str(run_dir))
        self.assertEqual(report.returncode, 0, report.stdout + report.stderr)

    def test_identical_ack_retry_preserves_completed_verified_handover(self) -> None:
        run_dir = self.init(target="codex", handshake="verified")
        ack_args = (
            "ack",
            "--run-dir",
            str(run_dir),
            "--target",
            "codex",
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        first_ack = self.run_handover(*ack_args)
        self.assertEqual(first_ack.returncode, 0, first_ack.stderr)
        confirm = self.run_handover("confirm", "--run-dir", str(run_dir))
        self.assertEqual(confirm.returncode, 0, confirm.stderr)
        ready = self.run_handover("ready", "--run-dir", str(run_dir), "--target", "codex")
        self.assertEqual(ready.returncode, 0, ready.stderr)

        ack_path = run_dir / "targets" / "codex" / "ack.json"
        acknowledged_at = json.loads(ack_path.read_text(encoding="utf-8"))["acknowledged_at"]
        before = self.run_handover("validate", "--run-dir", str(run_dir))
        self.assertEqual(before.returncode, 0, before.stdout + before.stderr)
        self.assertTrue(json.loads(before.stdout)["complete"])

        retry = self.run_handover(*ack_args)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertTrue(json.loads(retry.stdout)["reused"])
        self.assertEqual(
            json.loads(ack_path.read_text(encoding="utf-8"))["acknowledged_at"],
            acknowledged_at,
        )
        after = self.run_handover("validate", "--run-dir", str(run_dir))
        self.assertEqual(after.returncode, 0, after.stdout + after.stderr)
        self.assertTrue(json.loads(after.stdout)["complete"])

    def test_init_rejects_traversal_run_id(self) -> None:
        escaped = self.root / "escaped"
        result = self.run_handover(
            "init",
            "--cwd",
            str(self.cwd),
            "--out-root",
            str(self.out_root),
            "--run-id",
            "../escaped",
            "--task",
            "Do not escape",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((escaped / "handoff.json").exists())

    def test_init_rejects_traversal_target(self) -> None:
        result = self.run_handover(
            "init",
            "--cwd",
            str(self.cwd),
            "--out-root",
            str(self.out_root),
            "--run-id",
            "safe-run",
            "--target",
            "../escaped",
            "--task",
            "Do not escape",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.out_root / "safe-run" / "escaped" / "handoff.json").exists())

    def test_init_rejects_traversal_target_from_explicit_tag(self) -> None:
        result = self.run_handover(
            "init",
            "--cwd",
            str(self.cwd),
            "--out-root",
            str(self.out_root),
            "--run-id",
            "safe-run",
            "--target-from",
            "handover:../escaped",
            "--task",
            "Do not escape",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_init_rejects_run_directory_symlink_outside_out_root(self) -> None:
        self.out_root.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.out_root / "safe-run").symlink_to(outside, target_is_directory=True)

        result = self.run_handover(
            "init",
            "--cwd",
            str(self.cwd),
            "--out-root",
            str(self.out_root),
            "--run-id",
            "safe-run",
            "--target",
            "codex",
            "--task",
            "Do not escape",
            "--force",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((outside / "handoff.json").exists())

    def test_force_init_rejects_target_prompts_symlink_escape(self) -> None:
        run_dir = self.out_root / "safe-run"
        outside = self.root / "outside-prompts"
        outside.mkdir()
        run_dir.mkdir(parents=True)
        (run_dir / "target-prompts").symlink_to(outside, target_is_directory=True)

        result = self.run_handover(
            "init",
            "--cwd",
            str(self.cwd),
            "--out-root",
            str(self.out_root),
            "--run-id",
            "safe-run",
            "--target",
            "codex",
            "--task",
            "Do not escape",
            "--force",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((outside / "codex.txt").exists())

    def test_force_init_rejects_state_log_symlink_append(self) -> None:
        run_dir = self.out_root / "safe-run"
        outside_log = self.root / "outside-state.jsonl"
        sentinel = "outside must remain unchanged\n"
        outside_log.write_text(sentinel, encoding="utf-8")
        run_dir.mkdir(parents=True)
        (run_dir / "state.jsonl").symlink_to(outside_log)

        result = self.run_handover(
            "init",
            "--cwd",
            str(self.cwd),
            "--out-root",
            str(self.out_root),
            "--run-id",
            "safe-run",
            "--target",
            "codex",
            "--task",
            "Do not append outside the run directory",
            "--force",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outside_log.read_text(encoding="utf-8"), sentinel)

    def test_ack_and_ready_reject_traversal_target_loaded_from_handoff(self) -> None:
        run_dir = self.init(target="codex")
        handoff_path = run_dir / "handoff.json"
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        handoff["targets"] = [{"name": "../escaped", "status": "offered"}]
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

        ack = self.run_handover(
            "ack",
            "--run-dir",
            str(run_dir),
            "--target",
            "../escaped",
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        self.assertNotEqual(ack.returncode, 0)

        ready = self.run_handover(
            "ready",
            "--run-dir",
            str(run_dir),
            "--target",
            "../escaped",
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        self.assertNotEqual(ready.returncode, 0)
        self.assertFalse((run_dir / "escaped" / "ack.json").exists())
        self.assertFalse((run_dir / "escaped" / "ready.json").exists())

    def test_ready_rejects_traversal_run_id_loaded_from_handoff(self) -> None:
        run_dir = self.init(target="codex")
        handoff_path = run_dir / "handoff.json"
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        handoff["run_id"] = "../forged"
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

        result = self.run_handover(
            "ready",
            "--run-dir",
            str(run_dir),
            "--target",
            "codex",
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((run_dir / "targets" / "codex" / "ready.json").exists())

    def test_ready_and_validate_reject_corrupted_handshake_schema(self) -> None:
        run_dir = self.init(target="codex")
        handoff_path = run_dir / "handoff.json"
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        handoff["handshake"] = "downgraded"
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

        ready = self.run_handover(
            "ready",
            "--run-dir",
            str(run_dir),
            "--target",
            "codex",
            "--summary",
            "Understood",
            "--next-action",
            "Continue",
        )
        self.assertNotEqual(ready.returncode, 0)
        self.assertIn("handoff handshake", ready.stderr)
        self.assertFalse((run_dir / "targets" / "codex" / "ready.json").exists())

        report = self.run_handover("validate", "--run-dir", str(run_dir))
        self.assertNotEqual(report.returncode, 0)
        self.assertIn("handoff handshake", report.stderr)


if __name__ == "__main__":
    unittest.main()
