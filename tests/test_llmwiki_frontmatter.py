from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "llmwiki" / "frontmatter.py"
SPEC = importlib.util.spec_from_file_location("llmwiki_frontmatter", SCRIPT)
assert SPEC and SPEC.loader
FM = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FM
SPEC.loader.exec_module(FM)


class FrontmatterTest(unittest.TestCase):
    def test_parse_scalars_ints_and_lists(self) -> None:
        meta, body = FM.parse(
            "---\ntype: task\nid: T-0043\nsession_count: 2\n"
            "harnesses: [claude-code, codex]\n---\n\n## 목표\n"
        )
        self.assertEqual(meta["type"], "task")
        self.assertEqual(meta["session_count"], 2)
        self.assertEqual(meta["harnesses"], ["claude-code", "codex"])
        self.assertTrue(body.startswith("\n## 목표"))

    def test_parse_without_frontmatter_returns_body_unchanged(self) -> None:
        meta, body = FM.parse("# 그냥 문서\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "# 그냥 문서\n")

    def test_quote_protects_colon_space_and_leading_hash(self) -> None:
        self.assertEqual(FM.quote("foo: bar"), '"foo: bar"')
        self.assertEqual(FM.quote("#tag"), '"#tag"')
        self.assertEqual(FM.quote("*star"), '"*star"')
        self.assertEqual(FM.quote("[a]"), '"[a]"')

    def test_quote_leaves_plain_and_iso_timestamps_alone(self) -> None:
        self.assertEqual(FM.quote("ui-skills"), "ui-skills")
        self.assertEqual(FM.quote("2026-08-07T14:22:00+09:00"), "2026-08-07T14:22:00+09:00")

    def test_render_then_parse_survives_dangerous_title(self) -> None:
        meta = {"type": "task", "title": "fix: the: thing", "priority": 2}
        meta2, _ = FM.parse(FM.render(meta, "\n## 목표\n"))
        self.assertEqual(meta2["title"], "fix: the: thing")
        self.assertEqual(meta2["priority"], 2)

    def test_render_parse_is_stable_across_two_roundtrips(self) -> None:
        """닫는 --- 뒤 개행이 없으면 2회차에서 본문이 구분자에 붙어 깨진다."""
        meta, body = {"type": "task", "priority": 2}, "## 목표\n\n내용\n"
        once = FM.render(meta, body)
        m1, b1 = FM.parse(once)
        twice = FM.render(m1, b1)
        self.assertEqual(once, twice)
        m2, _ = FM.parse(twice)
        self.assertEqual(m2["priority"], 2)
        self.assertEqual(m2["type"], "task")

    def test_merge_overwrites_owned_and_preserves_unknown(self) -> None:
        existing = {"id": "T-0001", "status": "doing", "priority": 1, "mine": "keep"}
        merged = FM.merge(existing, {"session_count": 3, "status": "IGNORED"}, {"session_count"})
        self.assertEqual(merged["session_count"], 3)
        self.assertEqual(merged["status"], "doing")
        self.assertEqual(merged["priority"], 1)
        self.assertEqual(merged["mine"], "keep")


if __name__ == "__main__":
    unittest.main()
