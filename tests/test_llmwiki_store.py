from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "llmwiki" / "store.py"
SPEC = importlib.util.spec_from_file_location("llmwiki_store", SCRIPT)
assert SPEC and SPEC.loader
ST = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ST
SPEC.loader.exec_module(ST)


class StoreTest(unittest.TestCase):
    def test_append_then_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events.ndjson"
            ST.append_json(p, {"a": 1})
            ST.append_json(p, {"a": 2})
            rows, broken = ST.read_json(p)
            self.assertEqual([r["a"] for r in rows], [1, 2])
            self.assertEqual(broken, 0)

    def test_broken_line_is_skipped_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events.ndjson"
            ST.append_json(p, {"a": 1})
            with p.open("a", encoding="utf-8") as fh:
                fh.write('{"a": 2, "trunc\n')
            ST.append_json(p, {"a": 3})
            rows, broken = ST.read_json(p)
            self.assertEqual([r["a"] for r in rows], [1, 3])
            self.assertEqual(broken, 1)

    def test_missing_file_reads_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            rows, broken = ST.read_json(Path(d) / "nope.ndjson")
            self.assertEqual(rows, [])
            self.assertEqual(broken, 0)

    def test_state_defaults_and_update_persists(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            self.assertEqual(ST.load_state(p)["task_counter"], 0)

            def bump(s: dict) -> None:
                s["watermark"]["claude-mem"] = 42

            ST.update_state(p, bump)
            self.assertEqual(ST.load_state(p)["watermark"]["claude-mem"], 42)

    def test_next_task_id_increments_and_is_zero_padded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            self.assertEqual(ST.next_task_id(p), "T-0001")
            self.assertEqual(ST.next_task_id(p), "T-0002")
            self.assertEqual(ST.load_state(p)["task_counter"], 2)


if __name__ == "__main__":
    unittest.main()
