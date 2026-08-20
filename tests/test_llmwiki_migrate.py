from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import os
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


MG = _load("migrate")
ST = _load("store")

HOST = "mac-a"


@contextlib.contextmanager
def events_lock(events: Path):
    """Take the events lock the way an ingest would.

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


class RewriteDurabilityTest(unittest.TestCase):
    def test_unparsable_line_survives_the_rewrite(self) -> None:
        """events.ndjson is the only source the GEN sections rebuild from, so a
        torn line must be carried over, not dropped by the migration."""
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            events = home / "events.ndjson"
            ST.append_json(events, {"event_id": "claude-mem:7", "session_id": "s"})
            with events.open("a", encoding="utf-8") as fh:
                fh.write('{"event_id": "claude-mem:8", "sess\n')
            ST.append_json(events, {"event_id": "claude-mem:9", "session_id": "s3"})

            result = MG.namespace_events(home, HOST)

            self.assertEqual(result["migrated"], 2)
            self.assertEqual(result["broken_preserved"], 1)
            text = events.read_text(encoding="utf-8")
            self.assertIn('{"event_id": "claude-mem:8", "sess', text)
            rows, broken = ST.read_json(events)
            self.assertEqual(broken, 1)
            self.assertEqual([r["event_id"] for r in rows],
                             [f"claude-mem:{HOST}:7", f"claude-mem:{HOST}:9"])

    def test_append_during_the_rewrite_is_not_destroyed(self) -> None:
        """serve --refresh 60 ingests every minute. Without a lock the migration
        reads, an ingest appends, and os.replace throws that append away."""
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            events = home / "events.ndjson"
            ST.append_json(events, {"event_id": "claude-mem:7", "session_id": "s"})

            real_replace = os.replace

            def slow_replace(src, dst):
                # Widen the read-modify-write window so the race is deterministic.
                if str(dst).endswith("events.ndjson"):
                    time.sleep(0.4)
                real_replace(src, dst)

            appended: list[bool] = []

            def appender() -> None:
                time.sleep(0.1)
                with events_lock(events):
                    ST.append_json(events, {"event_id": f"claude-mem:{HOST}:8",
                                            "session_id": "s2"})
                    appended.append(True)

            worker = threading.Thread(target=appender)
            MG.os.replace = slow_replace
            try:
                worker.start()
                MG.namespace_events(home, HOST)
            finally:
                MG.os.replace = real_replace
                worker.join(10)

            self.assertEqual(appended, [True])
            rows, _ = ST.read_json(events)
            self.assertEqual({r["event_id"] for r in rows},
                             {f"claude-mem:{HOST}:7", f"claude-mem:{HOST}:8"})


if __name__ == "__main__":
    unittest.main()
