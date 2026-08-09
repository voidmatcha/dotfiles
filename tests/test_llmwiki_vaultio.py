from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "llmwiki" / "vaultio.py"
SPEC = importlib.util.spec_from_file_location("llmwiki_vaultio", SCRIPT)
assert SPEC and SPEC.loader
VIO = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VIO
SPEC.loader.exec_module(VIO)


class VaultIOTest(unittest.TestCase):
    def test_write_atomic_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.md"
            VIO.write_atomic(p, "hello\n")
            self.assertEqual(p.read_text(encoding="utf-8"), "hello\n")
            self.assertEqual([x.name for x in Path(d).iterdir()], ["a.md"])

    def test_write_page_skips_identical_content(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.md"
            self.assertTrue(VIO.write_page(p, {"type": "task"}, "\n본문\n"))
            before = p.stat().st_mtime_ns
            self.assertFalse(VIO.write_page(p, {"type": "task"}, "\n본문\n"))
            self.assertEqual(p.stat().st_mtime_ns, before)

    def test_read_page_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.md"
            VIO.write_page(p, {"type": "project", "sessions": 7}, "\n## 지금 상태\n")
            meta, body = VIO.read_page(p)
            self.assertEqual(meta["sessions"], 7)
            self.assertIn("지금 상태", body)

    def test_append_log_uses_fixed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            VIO.append_log(Path(d), "compile", "projects=3")
            VIO.append_log(Path(d), "ingest", "events=+2")
            lines = (Path(d) / "log.md").read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)
            self.assertRegex(lines[0], r"^## \[\d{4}-\d{2}-\d{2}\] compile \| projects=3$")
            self.assertIn("ingest | events=+2", lines[1])


if __name__ == "__main__":
    unittest.main()
