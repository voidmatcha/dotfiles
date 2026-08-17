from __future__ import annotations

import importlib.util
import sys
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parents[1] / "scripts" / "llmwiki"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"llmwiki_{name}", BASE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CP, ST, CFG, VIO, TK = (_load("compiler"), _load("store"), _load("config"),
                        _load("vaultio"), _load("tasks"))


def seed(home: Path, project: str, count: int, prefix: str = "s", when: str | None = None):
    at = when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(count):
        ST.append_json(home / "events.ndjson", {
            "event_id": f"claude-mem:{project}-{i}", "session_id": f"{prefix}{i}",
            "harness": "claude", "project": project, "at": at,
            "request": f"요청 {i}", "investigated": "", "learned": "", "completed": "",
            "next_steps": "다음", "notes": "", "files_read": [], "files_edited": [],
        })


class CompilerTest(unittest.TestCase):
    def test_creates_page_for_active_project_only(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "active-one", 5)
            seed(home, "tiny", 2, prefix="t")
            CP.run(home, vault, CFG.Config())
            self.assertTrue((vault / "projects" / "active-one.md").exists())
            self.assertFalse((vault / "projects" / "tiny.md").exists())

    def test_blocked_project_gets_no_page_of_its_own(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "yongjae", 30)
            CP.run(home, vault, CFG.Config(blocklist=frozenset({"yongjae"})))
            self.assertFalse((vault / "projects" / "yongjae.md").exists())

    def test_blocked_work_lands_in_unfiled_instead_of_vanishing(self) -> None:
        """Blocking suppresses a page; it does not erase the record.

        The blocklist exists to stop the junk pages that come from
        claude-mem taking the last component of cwd as the project name.
        But those names held 235 real work sessions - a personal blog,
        purplemux fixes, picking mentor candidates - and none of them
        showed up on any page. Starting a session from a shallow
        directory is not a reason to lose the record.
        """
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "yongjae", 30)
            CP.run(home, vault, CFG.Config(blocklist=frozenset({"yongjae"})))
            unfiled = vault / "projects" / "unfiled.md"
            self.assertTrue(unfiled.exists(), "차단된 작업이 사라졌다")
            self.assertIn("yongjae", unfiled.read_text(encoding="utf-8"),
                          "원래 어디서 왔는지 알 수 없으면 되돌릴 수 없다")

    def test_mapping_rescues_work_out_of_unfiled(self) -> None:
        """Unfiled must be reversible. That is what separates it from blocking."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "Documents", 30)
            cfg = CFG.Config(blocklist=frozenset({"Documents"}),
                             mapping={"Documents": "blog"})
            CP.run(home, vault, cfg)
            self.assertTrue((vault / "projects" / "blog.md").exists())
            self.assertFalse((vault / "projects" / "unfiled.md").exists())

    def test_unfiled_does_not_appear_without_blocked_work(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            self.assertFalse((vault / "projects" / "unfiled.md").exists())

    def test_is_idempotent_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            first = (vault / "projects" / "proj.md").read_bytes()
            CP.run(home, vault, CFG.Config())
            self.assertEqual((vault / "projects" / "proj.md").read_bytes(), first)

    def test_manual_sections_survive_recompile(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            page = vault / "projects" / "proj.md"
            meta, body = VIO.read_page(page)
            meta["priority"] = 1
            VIO.write_page(page, meta, body + "\n사람이 쓴 결론\n")
            CP.run(home, vault, CFG.Config())
            meta2, body2 = VIO.read_page(page)
            self.assertIn("사람이 쓴 결론", body2)
            self.assertEqual(meta2["priority"], 1)

    def test_index_lists_active_projects(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            self.assertIn("projects/proj.md", (vault / "index.md").read_text(encoding="utf-8"))

    def test_stale_project_is_archived_and_dropped_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            old = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
            seed(home, "ghost", 5, when=old)
            CP.run(home, vault, CFG.Config())
            meta, _ = VIO.read_page(vault / "projects" / "ghost.md")
            self.assertEqual(meta["status"], "archived")
            self.assertNotIn("projects/ghost.md", (vault / "index.md").read_text(encoding="utf-8"))

    def test_bindings_view_last_write_wins(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            for row in [
                {"session_id": "s1", "task_id": "T-0001", "dismissed": False,
                 "at": "2026-08-01T00:00:00Z"},
                {"session_id": "s1", "task_id": "T-0002", "dismissed": False,
                 "at": "2026-08-02T00:00:00Z"},
            ]:
                ST.append_json(home / "bindings.ndjson", row)
            self.assertEqual(CP.bindings_view(home)["s1"]["task_id"], "T-0002")

    def test_task_progress_accumulates_across_harnesses(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "proj", title="t")
            for i, harness in enumerate(("claude", "codex")):
                ST.append_json(home / "events.ndjson", {
                    "event_id": f"claude-mem:{i}", "session_id": f"s{i}", "harness": harness,
                    "project": "proj", "at": f"2026-08-0{i + 1}T00:00:00Z",
                    "request": f"요청{i}", "investigated": "", "learned": "", "completed": "",
                    "next_steps": "다음", "notes": "", "files_read": [], "files_edited": [],
                })
                TK.bind(home, f"s{i}", tid)
            CP.run(home, vault, CFG.Config())
            meta, body = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["session_count"], 2)
            self.assertEqual(meta["last_harness"], "codex")
            self.assertLess(body.index("claude"), body.index("codex"))

    def test_unbind_removes_session_from_progress(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "proj", title="t")
            ST.append_json(home / "events.ndjson", {
                "event_id": "claude-mem:1", "session_id": "s1", "harness": "claude",
                "project": "proj", "at": "2026-08-01T00:00:00Z", "request": "고유요청",
                "investigated": "", "learned": "", "completed": "", "next_steps": "",
                "notes": "", "files_read": [], "files_edited": [],
            })
            TK.bind(home, "s1", tid)
            CP.run(home, vault, CFG.Config())
            self.assertIn("고유요청", VIO.read_page(TK.path_for(vault, tid))[1])
            TK.unbind(home, "s1")
            CP.run(home, vault, CFG.Config())
            meta, body = VIO.read_page(TK.path_for(vault, tid))
            self.assertNotIn("고유요청", body)
            self.assertEqual(meta["session_count"], 0)

    def test_dangling_binding_does_not_crash_compile(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            ST.append_json(home / "bindings.ndjson", {
                "session_id": "s0", "task_id": "T-9999", "dismissed": False,
                "at": "2026-08-01T00:00:00Z",
            })
            result = CP.run(home, vault, CFG.Config())
            self.assertEqual(result["tasks"], 0)


if __name__ == "__main__":
    unittest.main()


class SlugTest(unittest.TestCase):
    def test_worktree_path_does_not_create_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "ui-skills/2026-06-27-adcker4", 5)
            CP.run(home, vault, CFG.Config())
            pages = list((vault / "projects").rglob("*.md"))
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0].parent, vault / "projects")
            self.assertNotIn("/", pages[0].stem)

    def test_safe_slug_keeps_korean_and_hyphens(self) -> None:
        self.assertEqual(CP.safe_slug("ui-skills"), "ui-skills")
        self.assertEqual(CP.safe_slug("ui-skills/2026-06"), "ui-skills-2026-06")
        self.assertEqual(CP.safe_slug("한글프로젝트"), "한글프로젝트")
        self.assertEqual(CP.safe_slug("///"), "unnamed")


class IdempotenceTest(unittest.TestCase):
    def test_whole_vault_including_log_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            CP.run(home, vault, CFG.Config())
            before = {p.relative_to(vault): p.read_bytes()
                      for p in sorted(vault.rglob("*")) if p.is_file()}
            CP.run(home, vault, CFG.Config())
            after = {p.relative_to(vault): p.read_bytes()
                     for p in sorted(vault.rglob("*")) if p.is_file()}
            self.assertEqual(before, after)


class VaultIdentityTest(unittest.TestCase):
    """Never let a vault swap pass silently.

    Measured: change the vault path, run compile, and a whole new vault
    appears at the new location while the old one stays on disk. The GEN
    regions are rebuilt from events, but prose outside the markers - the
    "지금 상태", "실패한 시도", "결정과 근거" sections - and the task pages
    live only in the vault, so they disappear. There was no warning at all.
    """

    def test_first_compile_stamps_the_vault(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            stamp = vault / ".llmwiki-vault"
            self.assertTrue(stamp.exists())
            self.assertIn(str(vault), stamp.read_text(encoding="utf-8"))

    def test_recompiling_the_same_vault_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            self.assertEqual(CP.run(home, vault, CFG.Config()).get("vault_warning"), None)

    def test_compiling_into_a_vault_stamped_elsewhere_warns(self) -> None:
        """Writing into a vault stamped elsewhere can overwrite human-written prose."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            moved = Path(d) / "moved"
            vault.rename(moved)
            result = CP.run(home, moved, CFG.Config())
            self.assertIsNotNone(result.get("vault_warning"))
            self.assertIn(str(vault), result["vault_warning"])

    def test_repointing_config_to_a_fresh_vault_warns(self) -> None:
        """The vault-side stamp alone cannot catch this case.

        The stamp travels with the vault, so it catches "the vault was
        moved" but not "the config was repointed at an empty new path" -
        that just stamps the new location and passes silently. Yet the
        latter is the accident actually observed: a whole new vault
        appears while the human-written prose and tasks/ are left behind.
        home is the one thing that does not change across a swap, so the
        last compiled vault path has to be recorded there.
        """
        with tempfile.TemporaryDirectory() as d:
            home, a, b = Path(d) / "h", Path(d) / "A", Path(d) / "B"
            seed(home, "proj", 5)
            CP.run(home, a, CFG.Config())
            result = CP.run(home, b, CFG.Config())
            self.assertIsNotNone(result.get("vault_warning"))
            self.assertIn(str(a), result["vault_warning"])

    def test_a_failed_compile_does_not_consume_the_swap_warning(self) -> None:
        """Updating state before the warning is emitted lets a failed run eat it.

        Repro: compile into A, repoint at an unwritable B, and run() dies
        mid-way with an exception. state already says B while the warning
        was never printed. Fix the permissions, run again, and it compiles
        quietly with no warning at all. A failed repoint is most common
        with an unmounted volume or a permissions problem.
        """
        with tempfile.TemporaryDirectory() as d:
            home, a, b = Path(d) / "h", Path(d) / "A", Path(d) / "B"
            seed(home, "proj", 5)
            CP.run(home, a, CFG.Config())

            (b / "projects").mkdir(parents=True)
            (b / "projects").chmod(0o500)
            try:
                with self.assertRaises(Exception):
                    CP.run(home, b, CFG.Config())
            finally:
                (b / "projects").chmod(0o700)

            result = CP.run(home, b, CFG.Config())
            self.assertIsNotNone(result.get("vault_warning"),
                                 "실패한 실행이 경고를 삼켰다")
            self.assertIn(str(a), result["vault_warning"])

    def test_home_remembers_the_vault_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            self.assertIsNone(CP.run(home, vault, CFG.Config()).get("vault_warning"))

    def test_vanished_stranded_vault_is_forgotten_without_a_swap(self) -> None:
        """Cleanup must not happen only on a swap.

        If the list is only touched at swap time, deleting the old vault
        still leaves its path in state. If something later appears at that
        same path - the default path is likely to be reused - the warning
        for an already finished swap comes back to life.
        """
        with tempfile.TemporaryDirectory() as d:
            home, a, b = Path(d) / "h", Path(d) / "A", Path(d) / "B"
            seed(home, "proj", 5)
            CP.run(home, a, CFG.Config())
            CP.run(home, b, CFG.Config())
            state = json.loads((home / "state.json").read_text())
            self.assertIn(str(a.resolve()), state["vaults_previous"])

            shutil.rmtree(a)
            CP.run(home, b, CFG.Config())
            state = json.loads((home / "state.json").read_text())
            self.assertEqual(state["vaults_previous"], [])

    def test_stamp_is_not_rewritten_on_every_run(self) -> None:
        """Idempotence. If the stamp changes every run, compile always writes."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            first = (vault / ".llmwiki-vault").read_bytes()
            CP.run(home, vault, CFG.Config())
            self.assertEqual(first, (vault / ".llmwiki-vault").read_bytes())
