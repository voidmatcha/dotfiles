from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import sqlite3
import sys
import tempfile
import threading
import time
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


IN = _load("ingest")
ST = _load("store")
CW = _load("cwdmap")
MG = _load("migrate")

HOST = "testhost"


def make_db(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE sdk_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          memory_session_id TEXT, platform_source TEXT NOT NULL DEFAULT 'claude');
        CREATE TABLE session_summaries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          memory_session_id TEXT NOT NULL, project TEXT NOT NULL,
          request TEXT, investigated TEXT, learned TEXT, completed TEXT,
          next_steps TEXT, files_read TEXT, files_edited TEXT, notes TEXT,
          created_at TEXT);
        """
    )
    for mem_id, platform in {(r[0], r[8]) for r in rows}:
        con.execute(
            "INSERT INTO sdk_sessions (memory_session_id, platform_source) VALUES (?,?)",
            (mem_id, platform),
        )
    for r in rows:
        con.execute(
            "INSERT INTO session_summaries "
            "(memory_session_id, project, request, investigated, learned, completed,"
            " next_steps, created_at) VALUES (?,?,?,?,?,?,?,?)",
            r[:8],
        )
    con.commit()
    con.close()


ROW_A = ("sess-a", "ui-skills", "req A", "inv", "learn", "done", "next A",
         "2026-08-01T00:00:00Z", "claude")
ROW_B = ("sess-b", "zeppelin", "req B", "inv", "learn", "done", "next B",
         "2026-08-02T00:00:00Z", "codex")


class IngestTest(unittest.TestCase):
    def test_imports_rows_and_advances_watermark(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, db = Path(d) / "home", Path(d) / "cm.db"
            make_db(db, [ROW_A, ROW_B])
            result = IN.run(home, db, HOST)
            self.assertEqual(result["imported"], 2)
            self.assertEqual(result["watermark"], 2)
            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual({e["harness"] for e in events}, {"claude", "codex"})
            self.assertEqual(events[0]["event_id"], f"claude-mem:{HOST}:1")
            self.assertEqual(events[0]["host"], HOST)

    def test_second_run_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, db = Path(d) / "home", Path(d) / "cm.db"
            make_db(db, [ROW_A])
            IN.run(home, db, HOST)
            second = IN.run(home, db, HOST)
            self.assertEqual(second["imported"], 0)
            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual(len(events), 1)

    def test_event_id_dedup_survives_watermark_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, db = Path(d) / "home", Path(d) / "cm.db"
            make_db(db, [ROW_A])
            IN.run(home, db, HOST)
            ST.update_state(home / "state.json",
                            lambda s: s["watermark"].update({f"claude-mem:{HOST}": 0}))
            IN.run(home, db, HOST)
            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual(len(events), 1)

    def test_snapshot_handles_wal_mode_source(self) -> None:
        """The real claude-mem DB is in WAL mode. If the copy stays WAL, it
        cannot be read."""
        with tempfile.TemporaryDirectory() as d:
            home, db = Path(d) / "home", Path(d) / "wal.db"
            make_db(db, [ROW_A])
            con = sqlite3.connect(db)
            con.execute("PRAGMA journal_mode = wal")
            con.close()
            result = IN.run(home, db, HOST)
            self.assertEqual(result["imported"], 1)

    def test_snapshot_does_not_mutate_source(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "src.db", Path(d) / "copy.db"
            make_db(src, [ROW_A])
            before = (src.stat().st_mtime_ns, src.stat().st_size)
            IN.snapshot_db(src, dst)
            self.assertTrue(dst.exists())
            self.assertEqual((src.stat().st_mtime_ns, src.stat().st_size), before)

    def test_cwd_record_overrides_claude_mem_project(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, db = Path(d) / "home", Path(d) / "cm.db"
            make_db(db, [ROW_A])
            home.mkdir(parents=True)
            CW.record(home, "sess-a", "/Users/me/Documents/zeppelin", "2026-07-31T00:00:00Z")
            IN.run(home, db, HOST)
            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual(events[0]["project"], "zeppelin")


@contextlib.contextmanager
def events_lock(events: Path):
    """Take the events lock the way a concurrent ingest would.

    Hand-rolled instead of calling store.lock_file so the test still runs against
    a store.py that has no lock at all, and fails on the assertion rather than on
    a missing attribute.
    """
    events.parent.mkdir(parents=True, exist_ok=True)
    lock_path = events.with_suffix(events.suffix + ".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class ConcurrentIngestTest(unittest.TestCase):
    def test_overlapping_runs_do_not_append_the_same_rows_twice(self) -> None:
        """The 60s web refresher and the 04:00 nightly job can overlap. Both see
        the same `s.id > watermark` rows, and a duplicated event later shows up
        as doubled merged_from."""
        with tempfile.TemporaryDirectory() as d:
            home, db = Path(d) / "home", Path(d) / "cm.db"
            make_db(db, [ROW_A, ROW_B])
            real_snapshot = IN.snapshot_db

            def slow_snapshot(src: Path, dst: Path) -> None:
                # Guarantee the two runs are actually in flight together.
                real_snapshot(src, dst)
                time.sleep(0.3)

            results: list[dict] = []
            lock = threading.Lock()

            def worker() -> None:
                out = IN.run(home, db, HOST)
                with lock:
                    results.append(out)

            IN.snapshot_db = slow_snapshot
            try:
                threads = [threading.Thread(target=worker) for _ in range(2)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(30)
            finally:
                IN.snapshot_db = real_snapshot

            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual(len(events), 2)
            self.assertEqual(len({e["event_id"] for e in events}), 2)
            self.assertEqual(sum(r["imported"] for r in results), 2)

    def test_run_skips_instead_of_crashing_when_the_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, db = Path(d) / "home", Path(d) / "cm.db"
            make_db(db, [ROW_A])
            events = home / "events.ndjson"
            with events_lock(events):
                result = IN.run(home, db, HOST)
            self.assertEqual(result["imported"], 0)
            self.assertTrue(result.get("locked"))
            self.assertFalse(events.exists())
            # A skipped run loses nothing: the next tick imports the same rows.
            later = IN.run(home, db, HOST)
            self.assertEqual(later["imported"], 1)
            self.assertFalse(later.get("locked"))


class MultiHostTest(unittest.TestCase):
    def test_same_rowid_on_two_hosts_does_not_collide(self) -> None:
        """claude-mem on both machines starts numbering rowids from 1.
        Without a host namespace, one machine's sessions silently vanish."""
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            for host, row in (("mac-a", ROW_A), ("mac-b", ROW_B)):
                db = Path(d) / f"{host}.db"
                make_db(db, [row])
                IN.run(home, db, host)
            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual(len(events), 2)
            self.assertEqual({e["host"] for e in events}, {"mac-a", "mac-b"})
            self.assertEqual(len({e["event_id"] for e in events}), 2)

    def test_watermarks_are_tracked_per_host(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            for host, row in (("mac-a", ROW_A), ("mac-b", ROW_B)):
                db = Path(d) / f"{host}.db"
                make_db(db, [row])
                IN.run(home, db, host)
            marks = ST.load_state(home / "state.json")["watermark"]
            self.assertEqual(set(marks), {"claude-mem:mac-a", "claude-mem:mac-b"})


class MigrateTest(unittest.TestCase):
    def test_legacy_ids_are_namespaced_and_watermark_moves(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            ST.append_json(home / "events.ndjson", {"event_id": "claude-mem:7", "session_id": "s"})
            ST.update_state(home / "state.json",
                            lambda s: s["watermark"].update({"claude-mem": 7}))
            result = MG.namespace_events(home, "mac-a")
            self.assertEqual(result["migrated"], 1)
            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual(events[0]["event_id"], "claude-mem:mac-a:7")
            self.assertEqual(events[0]["host"], "mac-a")
            marks = ST.load_state(home / "state.json")["watermark"]
            self.assertEqual(marks, {"claude-mem:mac-a": 7})

    def test_migration_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            ST.append_json(home / "events.ndjson", {"event_id": "claude-mem:7", "session_id": "s"})
            MG.namespace_events(home, "mac-a")
            again = MG.namespace_events(home, "mac-a")
            self.assertEqual(again["migrated"], 0)
            events, _ = ST.read_json(home / "events.ndjson")
            self.assertEqual(events[0]["event_id"], "claude-mem:mac-a:7")


if __name__ == "__main__":
    unittest.main()
