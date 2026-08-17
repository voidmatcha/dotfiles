from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
BASE = ROOT / "scripts" / "llmwiki"


def _load(name: str):
    key = f"llmwiki_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, BASE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


TK, ST, SN = _load("tasks"), _load("store"), _load("snapshot")


def run_cli(args: list[str], payload, home: Path, vault: Path):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-m", "scripts.llmwiki", *args],
        input=text, capture_output=True, text=True, cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "LLMWIKI_HOME": str(home),
            "LLMWIKI_VAULT": str(vault),
            "HOME": str(home.parent),
        },
    )


class HooksTest(unittest.TestCase):
    def test_session_start_autobinds_when_name_is_a_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", title="t")
            proc = run_cli(["hook-session-start"],
                           {"session_id": "s9", "session_name": tid, "cwd": str(vault)},
                           home, vault)
            self.assertEqual(proc.returncode, 0)
            rows, _ = ST.read_json(home / "bindings.ndjson")
            self.assertEqual(rows[-1]["task_id"], tid)
            self.assertEqual(rows[-1]["session_id"], "s9")

    def test_session_start_ignores_unknown_task_name(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            TK.create(home, vault, "p", title="t")
            run_cli(["hook-session-start"],
                    {"session_id": "s9", "session_name": "T-9999", "cwd": str(vault)},
                    home, vault)
            rows, _ = ST.read_json(home / "bindings.ndjson")
            self.assertEqual(rows, [])

    def test_session_start_brief_stays_under_budget(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            for _ in range(20):
                TK.create(home, vault, "p", title="제" * 100)
            # The basename of cwd is the project slug. Passing something other
            # than the task's project makes the filter drop everything, turning
            # this test into a vacuous check on an empty string.
            proc = run_cli(["hook-session-start"], {"session_id": "s1", "cwd": str(Path(d) / "p")},
                           home, vault)
            self.assertEqual(proc.returncode, 0)
            context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertTrue(context)
            self.assertLessEqual(len(context), 1000)

    def test_session_start_injects_only_the_cwd_project(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            mine = TK.create(home, vault, "alpha", title="내 프로젝트")
            other = TK.create(home, vault, "beta", title="남의 프로젝트")
            proc = run_cli(["hook-session-start"], {"session_id": "s1", "cwd": str(Path(d) / "alpha")},
                           home, vault)
            self.assertEqual(proc.returncode, 0)
            context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(mine, context)
            self.assertNotIn(other, context)

    def test_session_start_without_cwd_falls_back_to_all_projects(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "alpha", title="t")
            proc = run_cli(["hook-session-start"], {"session_id": "s1"}, home, vault)
            self.assertEqual(proc.returncode, 0)
            context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(tid, context)

    def test_user_prompt_records_cwd_once_per_change(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            for cwd in ("/w/a", "/w/a", "/w/b"):
                run_cli(["hook-user-prompt"], {"session_id": "s1", "cwd": cwd}, home, vault)
            rows, _ = ST.read_json(home / "cwd.ndjson")
            self.assertEqual([r["cwd"] for r in rows], ["/w/a", "/w/b"])

    def test_hooks_fail_open_on_garbage_input(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            for command in ("hook-session-start", "hook-user-prompt"):
                proc = run_cli([command], "not json at all", home, vault)
                self.assertEqual(proc.returncode, 0, command)

    def test_snapshot_rotates_and_restores(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault, dest = Path(d) / "h", Path(d) / "v", Path(d) / "backups"
            vault.mkdir(parents=True)
            (vault / "index.md").write_text("원본\n", encoding="utf-8")
            home.mkdir(parents=True)
            ST.append_json(home / "events.ndjson", {"event_id": "e1"})
            out = SN.run(vault, home, dest, keep=2, label="run0")
            self.assertEqual((out / "vault" / "index.md").read_text(encoding="utf-8"), "원본\n")
            self.assertTrue((out / "home" / "events.ndjson").exists())
            for i in range(1, 5):
                SN.run(vault, home, dest, keep=2, label=f"run{i}")
            self.assertLessEqual(len(list(dest.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
