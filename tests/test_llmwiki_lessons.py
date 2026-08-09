from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parents[1] / "scripts" / "llmwiki"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"llmwiki_{name}", BASE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LS, ST, CFG, CP, VIO = (_load("lessons"), _load("store"), _load("config"),
                        _load("compiler"), _load("vaultio"))


def seed(home: Path, project: str, session: str, learned: str,
         when: str | None = None) -> None:
    at = when or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ST.append_json(home / "events.ndjson", {
        "event_id": f"claude-mem:{session}", "session_id": session,
        "harness": "claude", "project": project, "at": at,
        "request": "요청", "investigated": "", "learned": learned,
        "completed": "", "next_steps": "", "notes": "",
        "files_read": [], "files_edited": [],
    })


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.home.mkdir()
        (self.vault / "projects").mkdir(parents=True)
        self.cfg = CFG.Config({})

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def page(self, project: str, body: str | None = None) -> Path:
        path = self.vault / "projects" / f"{project}.md"
        VIO.write_page(path, {"type": "project", "slug": project},
                       body if body is not None else CP.SKELETON)
        return path


class ScoringTest(Fixture):
    def test_failure_language_scores_above_plain_work(self) -> None:
        broke, _ = LS.score({"learned": "설정을 깨뜨려서 되돌렸다"})
        plain, _ = LS.score({"learned": "기능을 추가하고 문서를 갱신했다"})
        self.assertGreater(broke, plain)
        self.assertEqual(plain, 0)

    def test_english_and_korean_signals_both_count(self) -> None:
        _, ko = LS.score({"learned": "되돌렸다"})
        _, en = LS.score({"learned": "had to revert"})
        self.assertIn("되돌", ko)
        self.assertIn("revert", en)

    def test_signals_outside_scanned_fields_are_ignored(self) -> None:
        # request 는 사용자가 시킨 일이지 결과가 아니다. 여기 '실패'가 있다고
        # 실패한 시도가 되지는 않는다.
        total, _ = LS.score({"request": "실패한 테스트를 되돌려줘", "learned": ""})
        self.assertEqual(total, 0)


class CandidateTest(Fixture):
    def test_low_score_rows_are_not_offered(self) -> None:
        seed(self.home, "proj", "s1", "평범하게 기능을 추가했다")
        self.assertEqual(LS.candidates(self.home, self.cfg), [])

    def test_high_score_row_is_offered_with_ref(self) -> None:
        seed(self.home, "proj", "abcdef1234", "깨뜨려서 되돌렸다")
        rows = LS.candidates(self.home, self.cfg)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ref"], "abcdef12")

    def test_days_window_excludes_old_rows(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        seed(self.home, "proj", "s1", "깨뜨려서 되돌렸다", when=old)
        self.assertEqual(LS.candidates(self.home, self.cfg, days=30), [])
        self.assertEqual(len(LS.candidates(self.home, self.cfg, days=90)), 1)

    def test_missing_project_note_is_flagged_not_hidden(self) -> None:
        seed(self.home, "gone", "s1", "깨뜨려서 되돌렸다")
        rows = LS.candidates(self.home, self.cfg, vault=self.vault)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["note_exists"])

    def test_higher_score_outranks_more_recent(self) -> None:
        older = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        seed(self.home, "proj", "weak0000", "실패했다")
        seed(self.home, "proj", "strong00", "깨뜨려서 되돌리고 복구했다", when=older)
        rows = LS.candidates(self.home, self.cfg, min_score=1)
        self.assertEqual(rows[0]["ref"], "strong00")


class ResolveTest(Fixture):
    def test_ambiguous_prefix_refuses_instead_of_guessing(self) -> None:
        seed(self.home, "a", "dup00001", "깨뜨려서 되돌렸다")
        seed(self.home, "b", "dup00002", "깨뜨려서 되돌렸다")
        with self.assertRaises(KeyError) as caught:
            LS.resolve(self.home, self.cfg, "dup")
        self.assertIn("2건", str(caught.exception))

    def test_unknown_ref_raises(self) -> None:
        with self.assertRaises(KeyError):
            LS.resolve(self.home, self.cfg, "nope")


class AcceptTest(Fixture):
    def _cand(self, project: str = "proj", session: str = "abcdef1234") -> dict:
        seed(self.home, project, session, "깨뜨려서 되돌렸다")
        return LS.resolve(self.home, self.cfg, session[:8])

    def test_lesson_lands_under_the_heading(self) -> None:
        self.page("proj")
        cand = self._cand()
        LS.accept(self.home, self.vault, cand, "정규식으로 JSON 을 고치지 말 것")
        text = (self.vault / "projects" / "proj.md").read_text(encoding="utf-8")
        head = text.index(LS.HEADING)
        self.assertIn("정규식으로 JSON 을 고치지 말 것", text[head:text.index("## 결정과 근거")])

    def test_accepted_lesson_is_not_offered_again(self) -> None:
        self.page("proj")
        cand = self._cand()
        LS.accept(self.home, self.vault, cand, "교훈")
        self.assertEqual(LS.candidates(self.home, self.cfg), [])

    def test_dismissed_candidate_is_not_offered_again(self) -> None:
        cand = self._cand()
        LS.dismiss(self.home, cand, "그냥 남의 버그 고친 것")
        self.assertEqual(LS.candidates(self.home, self.cfg), [])

    def test_second_lesson_appends_below_the_first(self) -> None:
        self.page("proj")
        first = self._cand(session="aaaaaaaa11")
        LS.accept(self.home, self.vault, first, "첫째")
        second = self._cand(session="bbbbbbbb22")
        LS.accept(self.home, self.vault, second, "둘째")
        body = (self.vault / "projects" / "proj.md").read_text(encoding="utf-8")
        self.assertLess(body.index("첫째"), body.index("둘째"))
        self.assertLess(body.index("둘째"), body.index("## 결정과 근거"))

    def test_missing_project_note_refuses_rather_than_creating_one(self) -> None:
        cand = self._cand(project="gone")
        with self.assertRaises(FileNotFoundError):
            LS.accept(self.home, self.vault, cand, "교훈")
        self.assertFalse((self.vault / "projects" / "gone.md").exists())

    def test_blank_text_is_rejected(self) -> None:
        self.page("proj")
        cand = self._cand()
        with self.assertRaises(ValueError):
            LS.accept(self.home, self.vault, cand, "   ")

    def test_note_without_the_heading_refuses(self) -> None:
        self.page("proj", body="## 지금 상태\n\n## 결정과 근거\n")
        cand = self._cand()
        with self.assertRaises(ValueError):
            LS.accept(self.home, self.vault, cand, "교훈")

    def test_lesson_never_lands_inside_a_gen_block(self) -> None:
        """GEN 안에 들어가면 다음 compile 이 조용히 지운다.

        절 바로 뒤가 GEN 마커인 배치여야 이 분기를 실제로 지난다. 스켈레톤
        순서(실패한 시도 다음 결정과 근거)로는 '^## ' 가 먼저 걸려서 GEN
        경계 코드를 지우고도 테스트가 통과한다. 뮤테이션으로 확인했다.
        """
        self.page("proj", body=(
            "## 지금 상태\n\n"
            f"{LS.HEADING}\n\n"
            "<!-- GEN:timeline -->\n기존\n<!-- /GEN:timeline -->\n"
        ))
        cand = self._cand()
        LS.accept(self.home, self.vault, cand, "교훈")
        body = (self.vault / "projects" / "proj.md").read_text(encoding="utf-8")
        self.assertLess(body.index("교훈"), body.index("<!-- GEN:timeline -->"))
        self.assertNotIn("교훈", body[body.index("<!-- GEN:timeline -->"):])

    def test_lesson_survives_recompile(self) -> None:
        # 노트는 활성 임계치를 넘어야 생긴다. 여기서는 compile 이 만든 진짜
        # 노트여야 의미가 있어서 세션을 임계치만큼 채운다.
        for i in range(self.cfg.active_threshold):
            seed(self.home, "proj", f"filler{i:03d}", "평범한 작업")
        seed(self.home, "proj", "abcdef1234", "깨뜨려서 되돌렸다")
        CP.run(self.home, self.vault, self.cfg)
        cand = LS.resolve(self.home, self.cfg, "abcdef12")
        LS.accept(self.home, self.vault, cand, "지워지면 안 되는 교훈")
        CP.run(self.home, self.vault, self.cfg)
        body = (self.vault / "projects" / "proj.md").read_text(encoding="utf-8")
        self.assertIn("지워지면 안 되는 교훈", body)


if __name__ == "__main__":
    unittest.main()
