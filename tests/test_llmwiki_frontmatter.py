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
        """Without a newline after the closing ---, the second pass glues the
        body onto the delimiter and breaks it."""
        meta, body = {"type": "task", "priority": 2}, "## 목표\n\n내용\n"
        once = FM.render(meta, body)
        m1, b1 = FM.parse(once)
        twice = FM.render(m1, b1)
        self.assertEqual(once, twice)
        m2, _ = FM.parse(twice)
        self.assertEqual(m2["priority"], 2)
        self.assertEqual(m2["type"], "task")

    def test_block_style_list_survives_a_rewrite(self) -> None:
        """Obsidian's native block style used to parse to '' and be rewritten as
        tags: "", destroying the user's hand-written list."""
        text = "---\ntype: task\ntags:\n  - wiki\n  - personal\nid: T-0001\n---\n\n## 목표\n"
        meta, body = FM.parse(text)
        self.assertNotEqual(meta.get("tags"), "")
        self.assertEqual(FM.render(meta, body), text)

    def test_unowned_frontmatter_shapes_survive_byte_for_byte(self) -> None:
        """Nested maps, multi-line scalars, comments and null keys are not the
        compiler's to rewrite, so they must come back unchanged."""
        text = (
            "---\n"
            "# 손으로 쓴 주석\n"
            "type: project\n"
            "author:\n"
            "  name: 이용재\n"
            "  role: 유지보수\n"
            "note: >\n"
            "  여러 줄로 이어지는\n"
            "  설명\n"
            "cssclasses:\n"
            "- wide\n"
            "empty:\n"
            "\n"
            "slug: llmwiki\n"
            "---\n본문\n"
        )
        meta, body = FM.parse(text)
        self.assertEqual(FM.render(meta, body), text)
        self.assertEqual(meta["type"], "project")
        self.assertEqual(meta["slug"], "llmwiki")

    def test_owned_keys_still_rewrite_next_to_preserved_blocks(self) -> None:
        text = "---\nstatus: doing\ntags:\n  - wiki\n---\n본문\n"
        meta, body = FM.parse(text)
        meta["status"] = "done"
        self.assertEqual(FM.render(meta, body), "---\nstatus: done\ntags:\n  - wiki\n---\n본문\n")

    def test_quote_and_unquote_are_exact_inverses(self) -> None:
        """quote escaped but _unquote never unescaped, so backslashes doubled on
        every rewrite."""
        for value in (
            'he said: "no"',
            '"foo" bar',
            "back\\slash",
            "C:\\path: here",
            "trailing space ",
            "line: one\nline: two",
            "#해시로 시작",
            "일반 한글 제목",
            "quote' single: mark",
        ):
            with self.subTest(value=value):
                self.assertEqual(FM._unquote(FM.quote(value)), value)
                meta, _ = FM.parse(FM.render({"title": value}, "본문\n"))
                self.assertEqual(meta["title"], value)

    def test_dangerous_title_is_stable_across_repeated_compiles(self) -> None:
        meta, body = {"type": "task", "title": 'he said: "no"'}, "본문\n"
        text = FM.render(meta, body)
        for _ in range(3):
            meta, body = FM.parse(text)
            text = FM.render(meta, body)
        self.assertEqual(meta["title"], 'he said: "no"')
        self.assertEqual(text, FM.render(*FM.parse(text)))

    def test_quoted_leading_title_is_not_corrupted_once(self) -> None:
        meta, _ = FM.parse(FM.render({"title": '"foo" bar'}, "본문\n"))
        self.assertEqual(meta["title"], '"foo" bar')

    def test_list_items_with_commas_round_trip(self) -> None:
        meta, _ = FM.parse(FM.render({"harnesses": ["claude-code", "a, b"]}, "본문\n"))
        self.assertEqual(meta["harnesses"], ["claude-code", "a, b"])

    def test_merge_overwrites_owned_and_preserves_unknown(self) -> None:
        existing = {"id": "T-0001", "status": "doing", "priority": 1, "mine": "keep"}
        merged = FM.merge(existing, {"session_count": 3, "status": "IGNORED"}, {"session_count"})
        self.assertEqual(merged["session_count"], 3)
        self.assertEqual(merged["status"], "doing")
        self.assertEqual(merged["priority"], 1)
        self.assertEqual(merged["mine"], "keep")


if __name__ == "__main__":
    unittest.main()
