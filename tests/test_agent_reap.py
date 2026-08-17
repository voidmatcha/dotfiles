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


def proc(
    pid: int,
    ppid: int,
    pcpu: float,
    etime: str,
    args: str,
    user: str = "owner",
    mem: int = 0,
):
    return MODULE.Proc(pid, ppid, pcpu, mem, etime, user, args)


SERENA = (
    "/Users/o/.local/share/uv/tools/serena-agent/bin/python "
    "/Users/o/.local/bin/serena start-mcp-server --context codex --project-from-cwd"
)


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


class StaleMcpTest(unittest.TestCase):
    """Duplicate MCP servers under one live session: keep the youngest, reap the rest."""

    def _session(self, agent_pid: int, mcp_pids_etimes, agent: str = "codex"):
        table = {agent_pid: proc(agent_pid, 1, 1.0, "99:00", agent)}
        for pid, etime in mcp_pids_etimes:
            table[pid] = proc(pid, agent_pid, 0.0, etime, SERENA, mem=10_000)
        return table

    def test_keeps_youngest_mcp_per_session_and_reaps_older_duplicates(self) -> None:
        table = self._session(500, [(501, "03-14:00"), (502, "01-12:00"), (503, "20:00")])

        stale = MODULE.find_stale_mcp(table, 600, "owner", cwd_lookup=lambda _: "/repo")

        self.assertEqual(stale, {501, 502})

    def test_single_mcp_per_session_is_never_stale(self) -> None:
        table = self._session(500, [(501, "03-14:00")])

        stale = MODULE.find_stale_mcp(table, 600, "owner", cwd_lookup=lambda _: "/repo")

        self.assertEqual(stale, set())

    def test_same_args_but_different_cwd_are_not_duplicates(self) -> None:
        table = self._session(500, [(501, "03-14:00"), (502, "01-12:00")])
        cwds = {501: "/repo-a", 502: "/repo-b"}

        stale = MODULE.find_stale_mcp(table, 600, "owner", cwd_lookup=cwds.get)

        self.assertEqual(stale, set())

    def test_duplicates_in_different_sessions_are_not_collapsed(self) -> None:
        table = self._session(500, [(501, "03-14:00")])
        table.update(self._session(600, [(601, "03-14:00")]))

        stale = MODULE.find_stale_mcp(table, 600, "owner", cwd_lookup=lambda _: "/repo")

        self.assertEqual(stale, set())

    def test_young_duplicate_is_protected_by_min_age(self) -> None:
        table = self._session(500, [(501, "00:05"), (502, "00:02")])

        stale = MODULE.find_stale_mcp(table, 600, "owner", cwd_lookup=lambda _: "/repo")

        self.assertEqual(stale, set())

    def test_mcp_without_an_agent_ancestor_is_ignored(self) -> None:
        table = {
            700: proc(700, 1, 1.0, "99:00", "/opt/homebrew/bin/some-daemon"),
            701: proc(701, 700, 0.0, "03-14:00", SERENA),
            702: proc(702, 700, 0.0, "01-12:00", SERENA),
        }

        stale = MODULE.find_stale_mcp(table, 600, "owner", cwd_lookup=lambda _: "/repo")

        self.assertEqual(stale, set())


class MemoryRuleTest(unittest.TestCase):
    MEM_KB = 300 * 1024

    def test_idle_but_fat_agent_descendant_is_flagged_without_any_cpu(self) -> None:
        agent = proc(200, 10, 1.0, "30:00", "claude")
        chrome = proc(
            201, 200, 0.0, "40:00",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless",
            mem=800 * 1024,
        )
        table = {200: agent, 201: chrome}

        self.assertEqual(
            MODULE.classify(chrome, [200], table, 50, 600, "owner", self.MEM_KB),
            "AGENT-MEM",
        )

    def test_user_launched_chrome_is_out_of_reach_for_every_rule(self) -> None:
        launchd_chrome = proc(
            301, 1, 12.0, "99:00",
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper (Renderer)",
            mem=900 * 1024,
        )
        table = {301: launchd_chrome}

        self.assertIsNone(
            MODULE.classify(launchd_chrome, [], table, 50, 600, "owner", self.MEM_KB)
        )

    def test_small_agent_descendant_stays_below_the_memory_floor(self) -> None:
        agent = proc(200, 10, 1.0, "30:00", "claude")
        small = proc(201, 200, 0.0, "40:00", "node lsp.js", mem=20 * 1024)

        self.assertIsNone(
            MODULE.classify(small, [200], {200: agent, 201: small}, 50, 600, "owner", self.MEM_KB)
        )

    def test_young_fat_descendant_is_protected_by_min_age(self) -> None:
        agent = proc(200, 10, 1.0, "30:00", "claude")
        fresh = proc(201, 200, 0.0, "00:30", "node lsp.js", mem=900 * 1024)

        self.assertIsNone(
            MODULE.classify(fresh, [200], {200: agent, 201: fresh}, 50, 600, "owner", self.MEM_KB)
        )


class SubtreeTest(unittest.TestCase):
    def _tree(self):
        return {
            500: proc(500, 1, 1.0, "99:00", "codex"),
            501: proc(501, 500, 0.0, "03-14:00", SERENA, mem=10_000),
            502: proc(502, 501, 0.0, "03-14:00", "java jdtls", mem=20_000),
            503: proc(503, 502, 0.0, "03-14:00", "node bash-lsp", mem=5_000),
            504: proc(504, 500, 0.0, "03-14:00", SERENA, mem=10_000),
        }

    def test_descendants_walk_the_whole_subtree(self) -> None:
        self.assertEqual(sorted(MODULE.descendants(501, self._tree())), [502, 503])

    def test_subtree_mem_sums_the_process_and_all_its_children(self) -> None:
        self.assertEqual(MODULE.subtree_mem(501, self._tree()), 35_000)

    def test_kill_terminates_the_approved_pid_and_its_descendants(self) -> None:
        table = self._tree()
        candidate = table[501]

        with mock.patch.object(MODULE.os, "kill") as kill, \
                mock.patch.object(MODULE.time, "sleep"), \
                mock.patch.object(MODULE, "pid_alive", return_value=False), \
                redirect_stdout(io.StringIO()):
            status = MODULE.do_kill([("STALE-MCP", candidate)], [501], force=False, procs=table)

        self.assertEqual(status, 0)
        signalled = {call.args[0] for call in kill.call_args_list}
        self.assertEqual(signalled, {501, 502, 503})

    def test_kill_never_reaches_a_sibling_outside_the_approved_subtree(self) -> None:
        table = self._tree()
        candidate = table[501]

        with mock.patch.object(MODULE.os, "kill") as kill, \
                mock.patch.object(MODULE.time, "sleep"), \
                mock.patch.object(MODULE, "pid_alive", return_value=False), \
                redirect_stdout(io.StringIO()):
            MODULE.do_kill([("STALE-MCP", candidate)], [501], force=False, procs=table)

        signalled = {call.args[0] for call in kill.call_args_list}
        self.assertNotIn(504, signalled)
        self.assertNotIn(500, signalled)


AGENT_BROWSER = "/Users/o/.local/bin/agent-browser"
AGENT_CHROME = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
    "--user-data-dir=/var/folders/61/T/agent-browser-chrome-7fa5ed46"
)
USER_CHROME = (
    "/Applications/Google Chrome.app/Contents/Frameworks/"
    "Google Chrome Helper (Renderer).app/Contents/MacOS/Google Chrome Helper (Renderer)"
)
DEVTOOLS_MCP = "npm exec chrome-devtools-mcp@1.2.0"


class FootprintTest(unittest.TestCase):
    """ps RSS understates a swapped-out process by orders of magnitude."""

    def test_parses_every_unit_top_emits(self) -> None:
        cases = {
            "1922M": 1922 * 1024,
            "3920K": 3920,
            "2.1G": int(2.1 * 1024 * 1024),
            "512B": 0,
            "700": 700,
            "88M+": 88 * 1024,
        }
        for token, expected in cases.items():
            with self.subTest(token=token):
                self.assertEqual(MODULE.parse_mem_token(token), expected)

    def test_rejects_non_memory_tokens(self) -> None:
        for token in ("", "-", "abc", "1.2.3X"):
            with self.subTest(token=token):
                self.assertIsNone(MODULE.parse_mem_token(token))

    def test_footprint_beats_rss_when_top_reports_a_swapped_out_process(self) -> None:
        ps_out = "  67027     1   0.0    12288  03-11:11:51 owner java jdtls\n"
        top_out = "Processes: 2 total\n\n  PID    MEM  \n67027  1922M\n"

        def fake_run(cmd, **kw):
            text = top_out if cmd[0] == "top" else ps_out
            return mock.Mock(stdout=text)

        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            procs = MODULE.list_procs()

        self.assertEqual(procs[67027].mem, 1922 * 1024)

    def test_falls_back_to_rss_when_top_is_unavailable(self) -> None:
        ps_out = "  67027     1   0.0    12288  03-11:11:51 owner java jdtls\n"

        def fake_run(cmd, **kw):
            if cmd[0] == "top":
                raise OSError("top missing")
            return mock.Mock(stdout=ps_out)

        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            procs = MODULE.list_procs()

        self.assertEqual(procs[67027].mem, 12288)


class OrphanBrowserTest(unittest.TestCase):
    MEM_KB = 300 * 1024

    def test_launcher_reparented_to_launchd_is_flagged_while_completely_idle(self) -> None:
        p = proc(400, 1, 0.0, "16:19:08", AGENT_BROWSER, mem=5 * 1024)

        self.assertEqual(
            MODULE.classify(p, [], {400: p}, 50, 600, "owner", self.MEM_KB),
            "ORPHAN-BROWSER",
        )

    def test_orphaned_devtools_mcp_launcher_is_flagged_too(self) -> None:
        p = proc(401, 1, 0.0, "16:19:08", DEVTOOLS_MCP, mem=5 * 1024)

        self.assertEqual(
            MODULE.classify(p, [], {401: p}, 50, 600, "owner", self.MEM_KB),
            "ORPHAN-BROWSER",
        )

    def test_browser_still_owned_by_a_live_session_is_not_an_orphan(self) -> None:
        agent = proc(200, 10, 1.0, "30:00", "claude")
        p = proc(401, 200, 0.0, "16:19:08", AGENT_BROWSER, mem=5 * 1024)

        self.assertNotEqual(
            MODULE.classify(p, [200], {200: agent, 401: p}, 50, 600, "owner", self.MEM_KB),
            "ORPHAN-BROWSER",
        )

    def test_young_orphan_launcher_is_protected_by_min_age(self) -> None:
        p = proc(400, 1, 0.0, "00:30", AGENT_BROWSER, mem=5 * 1024)

        self.assertIsNone(
            MODULE.classify(p, [], {400: p}, 50, 600, "owner", self.MEM_KB)
        )

    def test_user_launched_chrome_is_never_mistaken_for_an_agent_browser(self) -> None:
        p = proc(301, 1, 0.0, "99:00", USER_CHROME, mem=900 * 1024)

        self.assertIsNone(
            MODULE.classify(p, [], {301: p}, 50, 600, "owner", self.MEM_KB)
        )


class DevtoolsMcpDedupTest(unittest.TestCase):
    def test_duplicate_devtools_mcp_servers_dedupe_like_serena(self) -> None:
        table = {
            500: proc(500, 1, 1.0, "99:00", "codex"),
            501: proc(501, 500, 0.0, "03-14:00", DEVTOOLS_MCP, mem=10_000),
            502: proc(502, 500, 0.0, "01-12:00", DEVTOOLS_MCP, mem=10_000),
            503: proc(503, 500, 0.0, "20:00", DEVTOOLS_MCP, mem=10_000),
        }

        stale = MODULE.find_stale_mcp(table, 600, "owner", cwd_lookup=lambda _: "/repo")

        self.assertEqual(stale, {501, 502})


class SummaryTest(unittest.TestCase):
    def test_summary_separates_agent_family_from_out_of_reach_chrome(self) -> None:
        table = {
            500: proc(500, 1, 1.0, "99:00", "codex"),
            501: proc(501, 500, 0.0, "03-14:00", SERENA, mem=100 * 1024),
            301: proc(
                301, 1, 12.0, "99:00",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome Helper (Renderer)",
                mem=900 * 1024,
            ),
        }

        summary = MODULE.memory_summary(table, "owner")

        self.assertEqual(summary["agent_family_kb"], 100 * 1024)
        self.assertEqual(summary["agent_family_count"], 1)
        self.assertEqual(summary["chrome_out_of_reach_kb"], 900 * 1024)

    def test_orphaned_browser_subtree_counts_as_agent_owned_not_out_of_reach(self) -> None:
        table = {
            400: proc(400, 1, 0.0, "16:19:08", AGENT_BROWSER, mem=5 * 1024),
            401: proc(401, 400, 0.0, "16:18:05", AGENT_CHROME, mem=60 * 1024),
            402: proc(402, 401, 0.0, "16:18:05", USER_CHROME, mem=500 * 1024),
        }

        summary = MODULE.memory_summary(table, "owner")

        self.assertEqual(summary["agent_family_kb"], 565 * 1024)
        self.assertEqual(summary["agent_family_count"], 3)
        self.assertEqual(summary["chrome_out_of_reach_kb"], 0)

    def test_a_real_user_browser_stays_out_of_reach(self) -> None:
        table = {301: proc(301, 1, 12.0, "99:00", USER_CHROME, mem=900 * 1024)}

        summary = MODULE.memory_summary(table, "owner")

        self.assertEqual(summary["agent_family_kb"], 0)
        self.assertEqual(summary["chrome_out_of_reach_kb"], 900 * 1024)


if __name__ == "__main__":
    unittest.main()
