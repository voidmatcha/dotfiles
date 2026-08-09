from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).parents[1] / "scripts" / "llmwiki"


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


TK, VIO, ST = _load("tasks"), _load("vaultio"), _load("store")


class TasksTest(unittest.TestCase):
    def test_create_without_bind_is_queued(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "ui-skills", title="배선 작업")
            self.assertEqual(tid, "T-0001")
            meta, body = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["status"], "queued")
            self.assertEqual(meta["project"], "ui-skills")
            self.assertIn("## 완료 조건", body)

    def test_create_with_bind_is_doing_and_writes_binding(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", title="t", bind_session="s1")
            meta, _ = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["status"], "doing")
            rows, _ = ST.read_json(home / "bindings.ndjson")
            self.assertEqual(rows[-1]["session_id"], "s1")
            self.assertEqual(rows[-1]["task_id"], tid)

    def test_title_defaults_to_first_sentence_of_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", next_steps_hint="배선을 끝낸다. 그다음 검증.")
            meta, _ = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["title"], "배선을 끝낸다")

    def test_rebind_returns_previous_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            self.assertIsNone(TK.bind(home, "s1", "T-0001"))
            self.assertEqual(TK.bind(home, "s1", "T-0002"), "T-0001")

    def test_unbind_appends_null_binding(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            TK.bind(home, "s1", "T-0001")
            TK.unbind(home, "s1")
            rows, _ = ST.read_json(home / "bindings.ndjson")
            self.assertIsNone(rows[-1]["task_id"])
            self.assertEqual(len(rows), 2)

    def test_dismiss_marks_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            self.assertEqual(TK.dismiss(home, ["s1", "s2"]), 2)
            rows, _ = ST.read_json(home / "bindings.ndjson")
            self.assertTrue(all(r["dismissed"] for r in rows))

    def test_set_status_changes_only_status(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", title="t")
            TK.set_status(vault, tid, "done")
            meta, _ = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["status"], "done")
            self.assertEqual(meta["project"], "p")

    def test_slugify_handles_korean_and_symbols(self) -> None:
        self.assertEqual(TK.slugify("fix: the thing!"), "fix-the-thing")
        self.assertTrue(TK.slugify("한글 제목"))


if __name__ == "__main__":
    unittest.main()
