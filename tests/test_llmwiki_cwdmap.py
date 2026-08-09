from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "llmwiki" / "cwdmap.py"
SPEC = importlib.util.spec_from_file_location("llmwiki_cwdmap", SCRIPT)
assert SPEC and SPEC.loader
CW = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CW
SPEC.loader.exec_module(CW)


class CwdMapTest(unittest.TestCase):
    def test_record_skips_consecutive_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            self.assertTrue(CW.record(home, "s1", "/w/a", "2026-08-01T00:00:00Z"))
            self.assertFalse(CW.record(home, "s1", "/w/a", "2026-08-01T00:01:00Z"))
            self.assertTrue(CW.record(home, "s1", "/w/b", "2026-08-01T00:02:00Z"))
            lines = (home / "cwd.ndjson").read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)

    def test_project_at_picks_interval_in_effect(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            CW.record(home, "s1", "/w/alpha", "2026-08-01T00:00:00Z")
            CW.record(home, "s1", "/w/beta", "2026-08-01T05:00:00Z")
            idx = CW.build(home)
            self.assertEqual(CW.project_at(idx, "s1", "2026-08-01T02:00:00Z", "fb"), "alpha")
            self.assertEqual(CW.project_at(idx, "s1", "2026-08-01T09:00:00Z", "fb"), "beta")

    def test_before_first_record_and_unknown_session_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            CW.record(home, "s1", "/w/alpha", "2026-08-01T05:00:00Z")
            idx = CW.build(home)
            self.assertEqual(CW.project_at(idx, "s1", "2026-08-01T00:00:00Z", "fb"), "fb")
            self.assertEqual(CW.project_at(idx, "nope", "2026-08-01T09:00:00Z", "fb"), "fb")


if __name__ == "__main__":
    unittest.main()
