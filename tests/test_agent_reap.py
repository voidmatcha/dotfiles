from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "agent_reap.py"
SPEC = importlib.util.spec_from_file_location("agent_reap", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def proc(pid: int, ppid: int, pcpu: float, etime: str, args: str, user: str = "owner"):
    return MODULE.Proc(pid, ppid, pcpu, etime, user, args)


class AgentReapTest(unittest.TestCase):
    def test_classifies_only_explainable_orphan_and_agent_child_shapes(self) -> None:
        orphan_inline = proc(101, 1, 80.0, "20:00", "python3 -c print(1)")
        self.assertEqual(
            MODULE.classify(orphan_inline, [], {101: orphan_inline}, 50, 600, "owner"),
            "ORPHAN-INLINE",
        )

        agent = proc(200, 10, 1.0, "30:00", "claude")
        child = proc(201, 200, 95.0, "20:00", "node worker.js")
        self.assertEqual(
            MODULE.classify(child, [200], {200: agent, 201: child}, 50, 600, "owner"),
            "AGENT-CHILD",
        )

        orphan_cpu = proc(301, 1, 80.0, "15:00", "/opt/homebrew/bin/zip archive.zip")
        self.assertEqual(
            MODULE.classify(orphan_cpu, [], {301: orphan_cpu}, 50, 600, "owner"),
            "ORPHAN-CPU",
        )

    def test_ignores_young_or_idle_inline_processes_reparented_to_launchd(self) -> None:
        cases = [
            proc(101, 1, 80.0, "00:01", "python3 -c print(1)"),
            proc(102, 1, 0.0, "20:00", "sh -c sleep 3600"),
        ]
        table = {item.pid: item for item in cases}

        for item in cases:
            with self.subTest(pid=item.pid):
                self.assertIsNone(MODULE.classify(item, [], table, 50, 600, "owner"))

    def test_excludes_agent_main_other_users_young_and_system_processes(self) -> None:
        cases = [
            proc(1, 0, 99.0, "99:00", "codex"),
            proc(2, 1, 99.0, "99:00", "python3 -c work", user="someone-else"),
            proc(3, 1, 99.0, "00:10", "node worker.js"),
            proc(4, 1, 99.0, "99:00", "/System/Library/CoreServices/task"),
        ]
        table = {item.pid: item for item in cases}
        for item in cases:
            with self.subTest(pid=item.pid):
                self.assertIsNone(MODULE.classify(item, [], table, 50, 600, "owner"))

    def test_protected_sets_stop_subtree_protection_at_nearest_agent(self) -> None:
        table = {
            100: proc(100, 50, 1.0, "00:01", "python3 agent_reap.py"),
            50: proc(50, 10, 1.0, "10:00", "claude"),
            10: proc(10, 1, 1.0, "20:00", "cmux"),
        }
        with mock.patch.object(MODULE.os, "getpid", return_value=100):
            exact, subtree_roots = MODULE.protected_sets(table)

        self.assertEqual(exact, {10, 50, 100})
        self.assertEqual(subtree_roots, {50, 100})

    def test_kill_rejects_pid_outside_the_fresh_candidate_set(self) -> None:
        candidate = proc(400, 1, 99.0, "99:00", "python3 -c work")
        stderr = io.StringIO()
        with redirect_stderr(stderr), mock.patch.object(MODULE.os, "kill") as kill:
            status = MODULE.do_kill([("ORPHAN-INLINE", candidate)], [401], force=False)

        self.assertEqual(status, 2)
        self.assertIn("not in current candidate set", stderr.getvalue())
        kill.assert_not_called()

    def test_candidate_table_emits_cwd_independent_kill_command(self) -> None:
        candidate = proc(400, 1, 99.0, "99:00", "python3 -c work")
        stdout = io.StringIO()

        with redirect_stdout(stdout), mock.patch.object(MODULE, "cwd_of", return_value="/tmp"):
            MODULE.print_table([("ORPHAN-INLINE", candidate)])

        output = stdout.getvalue()
        self.assertIn(str(SCRIPT_PATH.resolve()), output)
        self.assertIn(sys.executable, output)
        self.assertNotIn("python3 scripts/agent_reap.py", output)


if __name__ == "__main__":
    unittest.main()
