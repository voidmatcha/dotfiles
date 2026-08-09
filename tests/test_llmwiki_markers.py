from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "llmwiki" / "markers.py"
SPEC = importlib.util.spec_from_file_location("llmwiki_markers", SCRIPT)
assert SPEC and SPEC.loader
MK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MK
SPEC.loader.exec_module(MK)

DOC = """# 제목

사람이 쓴 줄

<!-- GEN:timeline -->
옛 내용
<!-- /GEN:timeline -->

끝줄
"""


class MarkersTest(unittest.TestCase):
    def test_replace_only_touches_inside_the_pair(self) -> None:
        out = MK.replace(DOC, "timeline", "새 내용")
        self.assertIn("사람이 쓴 줄", out)
        self.assertIn("끝줄", out)
        self.assertIn("새 내용", out)
        self.assertNotIn("옛 내용", out)

    def test_replace_is_idempotent(self) -> None:
        once = MK.replace(DOC, "timeline", "새 내용")
        twice = MK.replace(once, "timeline", "새 내용")
        self.assertEqual(once, twice)

    def test_missing_block_is_appended_and_body_preserved(self) -> None:
        out = MK.replace("기존 본문\n", "progress", "줄1")
        self.assertTrue(out.startswith("기존 본문\n"))
        self.assertIn("<!-- GEN:progress -->", out)
        self.assertIn("<!-- /GEN:progress -->", out)
        self.assertIn("줄1", out)

    def test_validate_passes_on_healthy_document(self) -> None:
        self.assertEqual(MK.validate(DOC), [])

    def test_validate_reports_unclosed_block(self) -> None:
        errs = MK.validate("<!-- GEN:a -->\n본문\n")
        self.assertTrue(any("a" in e for e in errs))

    def test_validate_reports_duplicate_name(self) -> None:
        text = "<!-- GEN:a -->\nx\n<!-- /GEN:a -->\n<!-- GEN:a -->\ny\n<!-- /GEN:a -->\n"
        self.assertTrue(MK.validate(text))

    def test_validate_reports_mismatched_close(self) -> None:
        self.assertTrue(MK.validate("<!-- GEN:a -->\nx\n<!-- /GEN:b -->\n"))

    def test_replace_refuses_damaged_document(self) -> None:
        with self.assertRaises(ValueError):
            MK.replace("<!-- GEN:a -->\n본문\n", "a", "새 내용")


if __name__ == "__main__":
    unittest.main()
