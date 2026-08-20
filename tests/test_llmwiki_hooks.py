from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


TK, ST, SN, VIO = _load("tasks"), _load("store"), _load("snapshot"), _load("vaultio")


def _has_tomllib() -> bool:
    try:
        import tomllib  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


# A test that writes a blocklist or a mapping into config.toml only holds if
# something can read it back. Without tomllib the loader raises by design
# rather than falling back to defaults, so skip instead of asserting less.
requires_tomllib = unittest.skipUnless(_has_tomllib(), "tomllib (python 3.11+) 필요")


def _main():
    """The CLI dispatcher itself. Named __main__.py, so importlib is the only
    way to reach its helpers without spawning a process."""
    key = "llmwiki_cli_main"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, BASE / "__main__.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


def write_config(home: Path, text: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(text, encoding="utf-8")


def run_cli(args: list[str], payload, home: Path, vault: Path,
            state: Path | None = None):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    env = {
        "PATH": "/usr/bin:/bin",
        "LLMWIKI_HOME": str(home),
        "LLMWIKI_VAULT": str(vault),
        "HOME": str(home.parent),
    }
    if state is not None:
        env["XDG_STATE_HOME"] = str(state)
    return subprocess.run(
        [sys.executable, "-m", "scripts.llmwiki", *args],
        input=text, capture_output=True, text=True, cwd=ROOT, env=env,
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

    def test_session_start_injects_a_project_name_that_is_not_slug_safe(self) -> None:
        """A directory whose name is not slug-safe must still get injection.

        The hook slugs the cwd basename ('My Project' -> 'My-Project') while
        `new` stored the raw string, and list_open compared the two with ==.
        The mismatch is silent: the project simply gets an empty context every
        session, forever, with nothing on stderr to say why.
        """
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "My Project", title="공백 이름")
            proc = run_cli(["hook-session-start"],
                           {"session_id": "s1", "cwd": str(Path(d) / "My Project")},
                           home, vault)
            self.assertEqual(proc.returncode, 0)
            context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(tid, context)

    @requires_tomllib
    def test_blocklisted_project_is_stored_and_injected_as_unfiled(self) -> None:
        """`new --project Documents` under a blocklist must not orphan the task.

        resolve_project sends a blocked name to 'unfiled', so that is the only
        identity any page or hook will ever look for. Storing 'Documents'
        produced a task nothing matched.
        """
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            write_config(home, 'blocklist = ["Documents"]\n')
            proc = run_cli(["new", "--project", "Documents", "--title", "차단된 이름"],
                           "", home, vault)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            tid = proc.stdout.strip()
            meta, _ = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["project"], "unfiled")
            proc = run_cli(["hook-session-start"],
                           {"session_id": "s1", "cwd": str(Path(d) / "Documents")},
                           home, vault)
            context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(tid, context)

    @requires_tomllib
    def test_mapped_worktree_name_is_stored_and_injected_as_its_target(self) -> None:
        """A mapped worktree name must resolve to the project it maps to.

        claude-mem reports worktrees as 'ui-skills/2026-06-27-adcker4' and the
        mapping folds them onto 'ui-skills'. A task stored under the raw
        worktree path belongs to a project page that does not exist.
        """
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            write_config(
                home,
                '[mapping]\n'
                '"ui-skills/2026-06-27-adcker4" = "ui-skills"\n'
                '"2026-06-27-adcker4" = "ui-skills"\n',
            )
            proc = run_cli(["new", "--project", "ui-skills/2026-06-27-adcker4",
                            "--title", "워크트리 작업"], "", home, vault)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            tid = proc.stdout.strip()
            meta, _ = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["project"], "ui-skills")
            # And a session started inside the worktree itself finds it.
            proc = run_cli(["hook-session-start"],
                           {"session_id": "s1",
                            "cwd": str(Path(d) / "ui-skills" / "2026-06-27-adcker4")},
                           home, vault)
            context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(tid, context)

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


DOCTOR = Path(__file__).parents[1] / "scripts" / "agent_tooling_doctor.py"


def _doctor():
    spec = importlib.util.spec_from_file_location("agent_tooling_doctor", DOCTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HookFailureIsDiscoverableTest(unittest.TestCase):
    """Fail-open must not mean fail-silent.

    The dispatcher swallowed every exception from a hook body and returned 0,
    and the shell wrapper only logs when python exits non-zero. So a corrupt
    bindings.ndjson, a full disk, or an unwritable LLMWIKI_HOME stopped all
    recording while every session looked healthy. This repo already lost two
    months of Codex history to exactly that pattern.
    """

    def _broken_home(self, d: str) -> Path:
        """An LLMWIKI_HOME that is a regular file.

        Any write under it raises when store.append_json calls mkdir, which is
        the same shape as an unwritable or full state directory. Config reads
        do not raise on it, so the failure lands inside the hook body - exactly
        where the guard used to eat it.
        """
        broken = Path(d) / "home-is-a-file"
        broken.write_text("", encoding="utf-8")
        return broken

    def _cases(self, d: str, vault: Path, tid: str):
        return (
            ("hook-session-start", "SessionStart",
             {"session_id": "s1", "session_name": tid, "cwd": str(vault)}),
            ("hook-user-prompt", "UserPromptSubmit",
             {"session_id": "s1", "cwd": str(Path(d) / "w")}),
        )

    def test_a_failing_hook_still_never_blocks_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", title="t")
            broken, state = self._broken_home(d), Path(d) / "state"
            for command, _label, payload in self._cases(d, vault, tid):
                proc = run_cli([command], payload, broken, vault, state=state)
                self.assertEqual(proc.returncode, 0, f"{command}: {proc.stderr}")

    def test_a_failing_hook_leaves_a_line_in_the_log(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", title="t")
            broken, state = self._broken_home(d), Path(d) / "state"
            for command, _label, payload in self._cases(d, vault, tid):
                run_cli([command], payload, broken, vault, state=state)

            log = state / "llmwiki" / "hook-errors.log"
            self.assertTrue(log.is_file(), "훅이 조용히 죽었다")
            lines = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2, lines)
            for line, (_c, label, _p) in zip(lines, self._cases(d, vault, tid)):
                # One line, tab separated, timestamp first - the format the
                # shell wrapper writes and the only one doctor counts.
                stamp, event, detail = line.split("\t")
                self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
                self.assertEqual(event, label)
                self.assertTrue(detail.strip(), "무슨 일이 났는지가 없으면 못 고친다")

    def test_the_logged_line_is_counted_by_doctor(self) -> None:
        """Writing somewhere doctor does not read is the same as not writing."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            TK.create(home, vault, "p", title="t")
            broken, state = self._broken_home(d), Path(d) / "state"
            run_cli(["hook-user-prompt"], {"session_id": "s1", "cwd": str(Path(d) / "w")},
                    broken, vault, state=state)

            doc = _doctor()
            log = state / "llmwiki" / "hook-errors.log"
            missing = Path(d) / "missing"
            with mock.patch.object(doc, "LLMWIKI_STATE", home), \
                 mock.patch.object(doc, "LLMWIKI_ERRLOG", log), \
                 mock.patch.object(doc, "LLMWIKI_PLIST", missing), \
                 mock.patch.object(doc, "CLAUDE_MEM_DB", missing), \
                 mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LLMWIKI_VAULT", None)
                rows = doc.check_llmwiki_capture(Path(d))
            self.assertTrue(any(s == "stale" and "훅 실패" in det for _, s, det in rows),
                            rows)

    def test_the_log_path_matches_the_shell_wrapper(self) -> None:
        """Three places resolve this path - the wrapper, doctor, and now the
        dispatcher. If they drift, doctor reads a green log while hooks die."""
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "state"
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state)}):
                self.assertEqual(_main().hook_log_path(),
                                 state / "llmwiki" / "hook-errors.log")
            # ${XDG_STATE_HOME:-...} treats an empty value as unset; .get() alone
            # would return "" and resolve the log to a relative path.
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "", "HOME": str(d)}):
                self.assertEqual(_main().hook_log_path(),
                                 Path(d) / ".local/state/llmwiki/hook-errors.log")

    def test_logging_a_failure_cannot_become_a_second_failure(self) -> None:
        """An unwritable state directory is one of the causes being caught, so
        the logger itself has to fail open."""
        with tempfile.TemporaryDirectory() as d:
            blocked = Path(d) / "blocked"
            blocked.write_text("", encoding="utf-8")  # not a directory
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(blocked)}):
                _main().log_hook_failure("hook-user-prompt", ValueError("boom"))


NIGHTLY_PLIST = (Path(__file__).parents[1] / "configs" / "llmwiki"
                 / "com.yongjae.llmwiki.plist")


class NightlyChainTest(unittest.TestCase):
    """The nightly job is ingest, compile, snapshot. The snapshot is the only
    copy of what exists nowhere but the vault, and under a bare `set -e` a
    failing compile ended the run before it. One damaged hand-edited page could
    stop every backup from that night on, silently."""

    def _chain(self) -> str:
        script = plistlib.loads(NIGHTLY_PLIST.read_bytes())["ProgramArguments"][-1]
        _head, sep, tail = script.partition('cd "$d"\n')
        self.assertTrue(sep, "plist 의 야간 체인 모양이 바뀌었다")
        return "set -e\n" + tail

    def _run(self, d: str, failing: str) -> tuple[int, list[str]]:
        stub, log = Path(d) / "py", Path(d) / "ran.log"
        # $3 is the subcommand in `"$py" -m scripts.llmwiki <cmd>`.
        stub.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$3" >> "$LOG"\n'
            f'[ "$3" != {failing} ] || exit 1\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        proc = subprocess.run(
            ["/bin/sh", "-c", f'py="{stub}"\n' + self._chain()],
            cwd=d, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin",
                                                        "LOG": str(log)},
        )
        ran = log.read_text(encoding="utf-8").split() if log.exists() else []
        return proc.returncode, ran

    def test_snapshot_runs_even_when_compile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code, ran = self._run(d, "compile")
            self.assertIn("snapshot", ran, "컴파일이 죽으면 백업이 사라진다")
            self.assertNotEqual(code, 0, "실패는 여전히 종료 코드로 보고돼야 한다")

    def test_snapshot_runs_even_when_ingest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code, ran = self._run(d, "ingest")
            self.assertEqual(ran, ["ingest", "compile", "snapshot"])
            self.assertNotEqual(code, 0)

    def test_a_clean_night_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code, ran = self._run(d, "nothing")
            self.assertEqual(ran, ["ingest", "compile", "snapshot"])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
