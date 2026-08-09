from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
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


LB, VIO = _load("library"), _load("vaultio")


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        (self.vault / "raw").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def drop(self, name: str, text: str = "본문") -> Path:
        path = self.vault / "raw" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def fill(self, slug: str, summary: str = "요약 내용") -> None:
        page = self.vault / "library" / f"{slug}.md"
        meta, body = VIO.read_page(page)
        VIO.write_page(page, meta, body.replace("## 요약\n", f"## 요약\n\n{summary}\n"))


class IngestTest(Fixture):
    def test_dropped_file_becomes_a_pending_note(self) -> None:
        self.drop("글.md")
        result = LB.ingest(self.vault)
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual([r["slug"] for r in LB.pending(self.vault)], ["글"])

    def test_same_file_twice_does_not_duplicate(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        again = LB.ingest(self.vault)
        self.assertEqual(again["created"], [])
        self.assertEqual(again["skipped"], 1)
        self.assertEqual(len(list((self.vault / "library").glob("*.md"))), 1)

    def test_identical_content_under_a_new_name_is_still_one_note(self) -> None:
        """같은 글을 다른 이름으로 다시 던져도 위키가 늘면 안 된다."""
        self.drop("a.md", "똑같은 본문")
        LB.ingest(self.vault)
        self.drop("b.md", "똑같은 본문")
        again = LB.ingest(self.vault)
        self.assertEqual(again["created"], [])
        self.assertEqual(len(list((self.vault / "library").glob("*.md"))), 1)

    def test_different_file_with_new_content_creates_a_second_note(self) -> None:
        self.drop("a.md", "첫 버전")
        LB.ingest(self.vault)
        self.drop("a2.md", "다른 글")
        self.assertEqual(len(LB.ingest(self.vault)["created"]), 1)

    def test_editing_a_raw_file_reports_change_instead_of_duplicating(self) -> None:
        """오타 하나 고쳤다고 노트가 늘면, 먼저 쓴 요약이 유령이 된다."""
        self.drop("a.md", "첫 버전")
        LB.ingest(self.vault)
        self.drop("a.md", "고친 버전")
        result = LB.ingest(self.vault)
        self.assertEqual(result["created"], [])
        self.assertEqual(result["changed"], ["a"])
        self.assertEqual(len(list((self.vault / "library").glob("*.md"))), 1)

    def test_same_stem_different_files_do_not_overwrite_each_other(self) -> None:
        self.drop("글.md", "하나")
        self.drop("sub/글.md", "둘")
        LB.ingest(self.vault)
        self.assertEqual(len(list((self.vault / "library").glob("*.md"))), 2)

    def test_dotfiles_and_ds_store_are_ignored(self) -> None:
        self.drop(".DS_Store", "쓰레기")
        self.drop(".hidden", "숨김")
        self.assertEqual(LB.ingest(self.vault)["created"], [])

    def test_note_records_source_and_stays_pending(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        meta, _ = VIO.read_page(self.vault / "library" / "글.md")
        self.assertEqual(meta["source"], "raw/글.md")
        self.assertEqual(meta["status"], "pending")

    def test_note_links_back_to_the_original(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        body = (self.vault / "library" / "글.md").read_text(encoding="utf-8")
        self.assertIn("[[raw/글.md]]", body)

    def test_missing_raw_directory_is_not_an_error(self) -> None:
        shutil.rmtree(self.vault / "raw")
        self.assertEqual(LB.ingest(self.vault)["created"], [])


class DoneTest(Fixture):
    def test_empty_summary_is_refused(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        with self.assertRaises(ValueError):
            LB.mark_done(self.vault, "글")

    def test_filled_summary_is_accepted_and_leaves_pending(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        self.fill("글")
        LB.mark_done(self.vault, "글")
        self.assertEqual(LB.pending(self.vault), [])

    def test_heading_only_does_not_count_as_filled(self) -> None:
        """제목만 있는 노트를 done 으로 넘기면 pending 이 거짓으로 빈다."""
        self.drop("글.md")
        LB.ingest(self.vault)
        page = self.vault / "library" / "글.md"
        meta, body = VIO.read_page(page)
        VIO.write_page(page, meta, body.replace("## 요약\n", "## 요약\n\n\n"))
        with self.assertRaises(ValueError):
            LB.mark_done(self.vault, "글")

    def test_text_in_a_later_section_does_not_count(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        page = self.vault / "library" / "글.md"
        meta, body = VIO.read_page(page)
        VIO.write_page(page, meta, body.replace("## 왜 담았나\n", "## 왜 담았나\n\n담은 이유\n"))
        with self.assertRaises(ValueError):
            LB.mark_done(self.vault, "글")

    def test_unknown_slug_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            LB.mark_done(self.vault, "없는것")

    def test_origin_is_recorded_without_touching_the_body(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        self.fill("글")
        before = VIO.read_page(self.vault / "library" / "글.md")[1]
        LB.set_origin(self.vault, "글", "https://example.com/a")
        meta, after = VIO.read_page(self.vault / "library" / "글.md")
        self.assertEqual(meta["origin"], "https://example.com/a")
        self.assertEqual(before, after)

    def test_origin_on_unknown_slug_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            LB.set_origin(self.vault, "없는것", "https://example.com")

    def test_resync_reopens_the_note_but_keeps_the_summary(self) -> None:
        self.drop("a.md", "첫 버전")
        LB.ingest(self.vault)
        self.fill("a", "사람이 쓴 요약")
        LB.mark_done(self.vault, "a")
        self.drop("a.md", "고친 버전")
        result = LB.resync(self.vault, "a")
        self.assertTrue(result["changed"])
        meta, body = VIO.read_page(self.vault / "library" / "a.md")
        self.assertEqual(meta["status"], "pending")
        self.assertIn("사람이 쓴 요약", body)

    def test_resync_on_an_unchanged_original_is_a_noop(self) -> None:
        self.drop("a.md", "첫 버전")
        LB.ingest(self.vault)
        self.fill("a")
        LB.mark_done(self.vault, "a")
        self.assertFalse(LB.resync(self.vault, "a")["changed"])
        meta, _ = VIO.read_page(self.vault / "library" / "a.md")
        self.assertEqual(meta["status"], "done")

    def test_resync_after_change_lets_ingest_settle(self) -> None:
        self.drop("a.md", "첫 버전")
        LB.ingest(self.vault)
        self.drop("a.md", "고친 버전")
        LB.resync(self.vault, "a")
        self.assertEqual(LB.ingest(self.vault)["changed"], [])

    def test_resync_with_a_deleted_original_raises(self) -> None:
        self.drop("a.md", "첫 버전")
        LB.ingest(self.vault)
        (self.vault / "raw" / "a.md").unlink()
        with self.assertRaises(FileNotFoundError):
            LB.resync(self.vault, "a")

    def test_done_note_is_not_reingested(self) -> None:
        self.drop("글.md")
        LB.ingest(self.vault)
        self.fill("글")
        LB.mark_done(self.vault, "글")
        self.assertEqual(LB.ingest(self.vault)["created"], [])


if __name__ == "__main__":
    unittest.main()
