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
        """Work happening right now under a blocked name must still show on
        the dashboard.

        This test originally asserted the opposite - that blocked names
        should drop out of the activity list. The result was that a session
        started from a shallow directory never appeared on the status page
        even while it was in progress. A tool built because losing the
        record was annoying was hiding work in progress.
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

    def test_list_open_cap_keeps_the_most_recently_active(self) -> None:
        """The cap must drop the stalest tasks, not the freshest.

        The hook injects only `limit` of them, so ascending order meant the
        session opened with the five tasks nobody had touched in months while
        the one worked on yesterday was cut. Every other view - the compile
        timeline, the Bases 진행 중 view - is most-recent-first.
        """
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            ids = {}
            for day in ("01", "02", "03", "04", "05", "06"):
                tid = TK.create(home, vault, "p", title=f"t{day}", bind_session=f"s{day}")
                page = TK.path_for(vault, tid)
                meta, body = VIO.read_page(page)
                meta["last_active"] = f"2026-01-{day}"
                VIO.write_page(page, meta, body)
                ids[day] = tid
            rows = QR.list_open(vault, "p")
            self.assertEqual([r["id"] for r in rows],
                             [ids["06"], ids["05"], ids["04"], ids["03"], ids["02"]])

    def test_list_open_keeps_doing_ahead_of_other_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            old_doing = TK.create(home, vault, "p", title="오래된 진행", bind_session="s1")
            fresh_queued = TK.create(home, vault, "p", title="새 대기")
            for tid, when in ((old_doing, "2026-01-01"), (fresh_queued, "2026-07-01")):
                page = TK.path_for(vault, tid)
                meta, body = VIO.read_page(page)
                meta["last_active"] = when
                VIO.write_page(page, meta, body)
            self.assertEqual([r["id"] for r in QR.list_open(vault, "p")],
                             [old_doing, fresh_queued])

    def test_list_open_does_not_drop_a_task_created_before_any_compile(self) -> None:
        """last_active is written by compile, which runs overnight.

        A task made today has an empty one, and sorting descending on "" would
        push it behind every stale task and off the end of the cap.
        """
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            for day in ("01", "02", "03", "04", "05"):
                tid = TK.create(home, vault, "p", title=f"t{day}", bind_session=f"s{day}")
                page = TK.path_for(vault, tid)
                meta, body = VIO.read_page(page)
                meta["last_active"] = f"2026-01-{day}"
                VIO.write_page(page, meta, body)
            brand_new = TK.create(home, vault, "p", title="오늘 만든 것", bind_session="s9")
            rows = QR.list_open(vault, "p")
            self.assertEqual(rows[0]["id"], brand_new)

    def test_list_open_matches_a_task_stored_under_a_raw_project_name(self) -> None:
        """Read-time normalization repairs vault rows written before the fix."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            VIO.write_page(vault / "tasks" / "T-0001-legacy.md", {
                "type": "task", "id": "T-0001", "title": "옛 태스크",
                "project": "Documents", "status": "doing",
            }, "본문\n")
            cfg = CFG.Config(blocklist=frozenset({"Documents"}))
            rows = QR.list_open(vault, "unfiled", cfg=cfg)
            self.assertEqual([r["id"] for r in rows], ["T-0001"])

    def test_brief_respects_char_budget(self) -> None:
        rows = [{"id": f"T-{i:04d}", "title": "제" * 200, "status": "doing"} for i in range(5)]
        self.assertLessEqual(len(QR.brief(rows, max_chars=1000)), 1000)


if __name__ == "__main__":
    unittest.main()


class LiveStatusTest(unittest.TestCase):
    def test_status_is_fresh_without_a_compile(self) -> None:
        """compile only runs overnight. Status must stay fresh in between."""
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            tid = TK.create(home, vault, "p", title="t", bind_session="s1")
            event(home, "e1", "s1", "p", recent(0), edited=["a.py"])
            meta, _ = VIO.read_page(TK.path_for(vault, tid))
            self.assertEqual(meta["last_active"], "")  # compile has not written yet

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
        """Having no activity record must not mark a just-created task stale."""
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
