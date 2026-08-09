from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).parents[1] / "scripts" / "llmwiki"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"llmwiki_{name}", BASE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MG = _load("merge")
RD = _load("render")


def ev(eid, sid, project, at, request="", nxt="", edited=None):
    return {
        "event_id": eid, "session_id": sid, "harness": "claude", "project": project,
        "at": at, "request": request, "investigated": "", "learned": "",
        "completed": "", "next_steps": nxt, "notes": "",
        "files_read": [], "files_edited": edited or [],
    }


class MergeTest(unittest.TestCase):
    def test_folds_one_session_into_one_row(self) -> None:
        rows = MG.by_session_project([
            ev("e1", "s1", "p", "2026-08-01T00:00:00Z", request="첫 요청", nxt="다음1", edited=["a.py"]),
            ev("e2", "s1", "p", "2026-08-01T01:00:00Z", request="중간", nxt="다음2", edited=["b.py"]),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request"], "첫 요청")
        self.assertEqual(rows[0]["next_steps"], "다음2")
        self.assertEqual(rows[0]["merged_from"], 2)
        self.assertEqual(sorted(rows[0]["files_edited"]), ["a.py", "b.py"])
        self.assertEqual(rows[0]["at"], "2026-08-01T01:00:00Z")

    def test_same_session_two_projects_yields_two_rows(self) -> None:
        rows = MG.by_session_project([
            ev("e1", "s1", "alpha", "2026-08-01T00:00:00Z"),
            ev("e2", "s1", "beta", "2026-08-01T01:00:00Z"),
        ])
        self.assertEqual({r["project"] for r in rows}, {"alpha", "beta"})
        self.assertEqual([r["merged_from"] for r in rows], [1, 1])

    def test_rows_are_sorted_by_time(self) -> None:
        rows = MG.by_session_project([
            ev("e2", "s2", "p", "2026-08-02T00:00:00Z"),
            ev("e1", "s1", "p", "2026-08-01T00:00:00Z"),
        ])
        self.assertEqual([r["session_id"] for r in rows], ["s1", "s2"])

    def test_progress_line_flags_compression_and_truncates(self) -> None:
        row = MG.by_session_project([
            ev(f"e{i}", "s1", "p", f"2026-08-01T0{i}:00:00Z", request="x" * 200, nxt="y" * 300)
            for i in range(2)
        ])[0]
        line = RD.progress_line(row, 120, 200)
        self.assertIn("(요약 2건 압축)", line)
        self.assertIn("x" * 120, line)
        self.assertNotIn("x" * 121, line)

    def test_progress_line_omits_flag_for_single_event(self) -> None:
        row = MG.by_session_project([ev("e1", "s1", "p", "2026-08-01T00:00:00Z", request="짧음")])[0]
        self.assertNotIn("압축", RD.progress_line(row, 120, 200))

    def test_timeline_line_shows_task_link_when_bound(self) -> None:
        row = MG.by_session_project([ev("e1", "s1", "p", "2026-08-01T00:00:00Z", request="R")])[0]
        self.assertIn("[[T-0043]]", RD.timeline_line(row, "T-0043"))
        self.assertNotIn("[[", RD.timeline_line(row, None))


if __name__ == "__main__":
    unittest.main()
