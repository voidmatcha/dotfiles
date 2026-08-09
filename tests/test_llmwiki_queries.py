from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


QR, TK, ST, CFG, VIO = (_load("queries"), _load("tasks"), _load("store"),
                        _load("config"), _load("vaultio"))


def recent(days: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def event(home: Path, eid: str, sid: str, project: str, when: str,
          nxt: str = "다음", edited=None):
    ST.append_json(home / "events.ndjson", {
        "event_id": eid, "session_id": sid, "harness": "claude", "project": project,
        "at": when, "request": "req", "investigated": "", "learned": "", "completed": "",
        "next_steps": nxt, "notes": "", "files_read": [], "files_edited": edited or [],
    })


class QueriesTest(unittest.TestCase):
    def test_unclassified_requires_work_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            event(home, "e1", "thin", "p", recent(1))
            event(home, "e2", "fat", "p", recent(1))
            event(home, "e3", "fat", "p", recent(1))
            event(home, "e4", "edited", "p", recent(1), edited=["a.py"])
            found = {r["session_id"] for r in QR.unclassified(home, CFG.Config())}
            self.assertEqual(found, {"fat", "edited"})

    def test_unclassified_excludes_bound_and_dismissed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            event(home, "e1", "bound", "p", recent(1), edited=["a.py"])
            event(home, "e2", "gone", "p", recent(1), edited=["b.py"])
            TK.bind(home, "bound", "T-0001")
            TK.dismiss(home, ["gone"])
            self.assertEqual(QR.unclassified(home, CFG.Config()), [])

    def test_unclassified_respects_the_day_window(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            event(home, "e1", "old", "p", recent(60), edited=["a.py"])
            self.assertEqual(QR.unclassified(home, CFG.Config()), [])

    def test_unclassified_filters_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            event(home, "e1", "a", "alpha", recent(1), edited=["a.py"])
            event(home, "e2", "b", "beta", recent(1), edited=["b.py"])
            rows = QR.unclassified(home, CFG.Config(), project="alpha")
            self.assertEqual([r["session_id"] for r in rows], ["a"])

    def test_blocked_projects_show_as_unfiled_not_hidden(self) -> None:
        """차단된 이름으로 지금 작업 중이면 대시보드에 보여야 한다.

        이 테스트는 원래 반대를 주장했다 - 차단된 것은 활동 목록에서 빠져야
        한다고. 그 결과 얕은 디렉터리에서 시작한 세션은 진행 중인데도 상태
        페이지에 나타나지 않았다. 기록이 안 남는 게 불편해서 만든 도구가
        진행 중인 일을 숨기고 있었다.
        """
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            event(home, "e1", "a", "keep", recent(1), edited=["a.py"])
            event(home, "e2", "b", "junk", recent(1), edited=["b.py"])
            cfg = CFG.Config(blocklist=frozenset({"junk"}))
            self.assertEqual(sorted(r["project"] for r in QR.activity(home, cfg)),
                             ["keep", "unfiled"])

    def test_activity_aggregates_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            event(home, "e1", "a", "alpha", recent(1), edited=["a.py"])
            event(home, "e2", "b", "alpha", recent(1), edited=["b.py"])
            event(home, "e3", "c", "beta", recent(1))
            rows = {r["project"]: r for r in QR.activity(home, CFG.Config())}
            self.assertEqual(rows["alpha"]["sessions"], 2)
            self.assertEqual(rows["alpha"]["unclassified"], 2)

    def test_status_separates_doing_stale_and_queued(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            fresh = TK.create(home, vault, "p", title="fresh", bind_session="s1")
            stale = TK.create(home, vault, "p", title="stale", bind_session="s2")
            queued = TK.create(home, vault, "p", title="queued")
            for tid, when in ((fresh, recent(1)), (stale, recent(9))):
                page = TK.path_for(vault, tid)
                meta, body = VIO.read_page(page)
                meta["last_active"] = when[:10]
                VIO.write_page(page, meta, body)
            result = QR.status(home, vault, CFG.Config())
            self.assertIn(stale, [t["id"] for t in result["stale"]])
            self.assertNotIn(stale, [t["id"] for t in result["doing"]])
            self.assertIn(queued, [t["id"] for t in result["queued"]])

    def test_brief_respects_char_budget(self) -> None:
        rows = [{"id": f"T-{i:04d}", "title": "제" * 200, "status": "doing"} for i in range(5)]
        self.assertLessEqual(len(QR.brief(rows, max_chars=1000)), 1000)


if __name__ == "__main__":
    unittest.main()


class LiveStatusTest(unittest.TestCase):
    def test_status_is_fresh_without_a_compile(self) -> None:
        """compile 은 야간에만 돈다. 그 사이에도 상태가 신선해야 한다."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", title="t", bind_session="s1")
            event(home, "e1", "s1", "p", recent(0), edited=["a.py"])
            meta, _ = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["last_active"], "")  # compile 이 아직 안 씀

            doing = QR.status(home, vault, CFG.Config())["doing"]
            self.assertEqual(len(doing), 1)
            self.assertTrue(doing[0]["last_active"])
            self.assertEqual(doing[0]["session_count"], 1)

    def test_live_overlay_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            TK.create(home, vault, "p", title="t", bind_session="s1")
            event(home, "e1", "s1", "p", recent(0), edited=["a.py"])
            result = QR.status(home, vault, CFG.Config(), live=False)
            self.assertEqual(result["doing"][0]["last_active"], "")
            self.assertEqual(result["stale"], [])

    def test_brand_new_task_is_not_flagged_stale(self) -> None:
        """활동 기록이 없다고 방금 만든 태스크를 정체로 표시하면 안 된다."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            TK.create(home, vault, "p", title="t", bind_session="s1")
            result = QR.status(home, vault, CFG.Config())
            self.assertEqual(result["stale"], [])
            self.assertEqual(len(result["doing"]), 1)

    def test_live_activity_tracks_latest_harness(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            TK.bind(home, "s1", "T-0001")
            ST.append_json(home / "events.ndjson", {
                "event_id": "e1", "session_id": "s1", "harness": "claude", "project": "p",
                "at": "2026-08-01T00:00:00Z", "request": "", "next_steps": "",
                "files_read": [], "files_edited": [],
            })
            ST.append_json(home / "events.ndjson", {
                "event_id": "e2", "session_id": "s1", "harness": "codex", "project": "p",
                "at": "2026-08-02T00:00:00Z", "request": "", "next_steps": "",
                "files_read": [], "files_edited": [],
            })
            live = QR.live_activity(home)["T-0001"]
            self.assertEqual(live["last_harness"], "codex")
            self.assertEqual(live["last_active"][:10], "2026-08-02")
