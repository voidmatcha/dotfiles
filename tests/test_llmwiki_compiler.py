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
        """차단은 페이지를 막는 것이지 기록을 지우는 것이 아니다.

        블록리스트는 cwd 의 마지막 이름이 프로젝트가 되는 claude-mem 의 방식
        때문에 생긴 잡동사니 페이지를 막으려고 만들었다. 그런데 그 이름들
        안에 실제 작업 235건이 들어 있었고 - 개인 블로그, purplemux 수정,
        멘토 후보 선정 - 전부 어느 페이지에도 나타나지 않았다. 얕은
        디렉터리에서 세션을 시작했다는 것이 기록을 잃을 이유가 될 수 없다.
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
        """미분류는 되돌릴 수 있어야 한다. 그게 차단과의 차이다."""
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
    """볼트 교체를 조용히 넘기지 않는다.

    실측: 볼트 경로를 바꾸고 compile 하면 새 위치에 볼트가 통째로 생기고
    옛 볼트는 디스크에 그대로 남는다. GEN 영역은 events 에서 되살아나지만
    마커 밖의 글 - 지금 상태, 실패한 시도, 결정과 근거 - 과 태스크 페이지는
    볼트에만 있어서 사라진다. 아무 경고도 없었다.
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
        """다른 곳에서 온 볼트에 쓰면 사람이 쓴 글을 덮어쓸 수 있다."""
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
        """볼트 쪽 표식만으로는 이 경우를 잡을 수 없다.

        표식은 볼트와 함께 움직이므로 '옮긴 볼트' 는 잡지만 '설정을 빈 새
        경로로 돌린' 경우는 새 위치에 표식을 찍고 조용히 넘어간다. 그런데
        후자가 실제로 측정된 사고 - 사람이 쓴 글과 tasks/ 를 남겨둔 채 새
        볼트가 통째로 생긴다. 교체를 가로질러 변하지 않는 것은 home 이므로
        마지막으로 컴파일한 볼트 경로를 거기에 적어야 한다.
        """
        with tempfile.TemporaryDirectory() as d:
            home, a, b = Path(d) / "h", Path(d) / "A", Path(d) / "B"
            seed(home, "proj", 5)
            CP.run(home, a, CFG.Config())
            result = CP.run(home, b, CFG.Config())
            self.assertIsNotNone(result.get("vault_warning"))
            self.assertIn(str(a), result["vault_warning"])

    def test_a_failed_compile_does_not_consume_the_swap_warning(self) -> None:
        """경고가 나오기 전에 state 를 갱신하면 실패한 실행이 그것을 삼킨다.

        재현: A 에서 컴파일 → 쓸 수 없는 B 로 재지정 → run() 이 도중에
        예외로 죽는다. 그런데 state 는 이미 B 라고 적혔고 경고는 출력되지
        않았다. 권한을 고치고 다시 돌리면 아무 경고 없이 조용히 컴파일된다.
        재지정 실패는 마운트 안 된 볼륨이나 권한 문제에서 가장 흔하다.
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
        """정리는 교체할 때만 일어나면 안 된다.

        목록을 교체 시점에만 손보면, 옛 볼트를 지운 뒤에도 그 경로가 state 에
        남는다. 나중에 같은 경로에 무언가 생기면 - 기본 경로는 재사용될 만하다
        - 이미 끝난 교체에 대한 경고가 되살아난다.
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
        """멱등성. 스탬프가 매번 바뀌면 compile 이 항상 변경을 만든다."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            seed(home, "proj", 5)
            CP.run(home, vault, CFG.Config())
            first = (vault / ".llmwiki-vault").read_bytes()
            CP.run(home, vault, CFG.Config())
            self.assertEqual(first, (vault / ".llmwiki-vault").read_bytes())
