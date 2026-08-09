from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).parents[1] / "scripts" / "llmwiki"


def _load(name: str):
    key = f"llmwiki_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, BASE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


WV, CFG = _load("webview"), _load("config")


class ResolveTest(unittest.TestCase):
    def _vault(self, d: str) -> Path:
        vault = Path(d) / "v"
        (vault / "projects").mkdir(parents=True)
        (vault / "tasks").mkdir(parents=True)
        (vault / "projects" / "alpha.md").write_text("# alpha\n", encoding="utf-8")
        (vault / "tasks" / "T-0001-x.md").write_text("# t\n", encoding="utf-8")
        (vault / "index.md").write_text("# index\n", encoding="utf-8")
        for folder, stem in (("rest", "아스테로이드 시티"), ("library", "어떤자료")):
            (vault / folder).mkdir(parents=True)
            (vault / folder / f"{stem}.md").write_text(
                f"---\ntype: {folder}\nstatus: todo\nkind: 영화\n---\n# {stem}\n",
                encoding="utf-8",
            )
        return vault

    def test_resolves_project_task_and_root_pages(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            self.assertIsNotNone(WV.resolve_page(vault, "alpha"))
            self.assertIsNotNone(WV.resolve_page(vault, "T-0001"))
            self.assertIsNotNone(WV.resolve_page(vault, "index"))

    def test_resolves_rest_and_library_pages(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            self.assertIsNotNone(WV.resolve_page(vault, "어떤자료"))

    def test_title_with_a_space_resolves(self) -> None:
        """공백을 막으면 그 노트만 조용히 404 가 된다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            self.assertIsNotNone(WV.resolve_page(vault, "아스테로이드 시티"))

    def test_allowing_spaces_did_not_open_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (Path(d) / "secret.md").write_text("비밀\n", encoding="utf-8")
            for bad in (".. / secret", "a /../secret", " ../secret", "a/../../secret"):
                self.assertIsNone(WV.resolve_page(vault, bad), bad)

    def test_nested_snapshot_path_resolves(self) -> None:
        """공고 원본은 library/jobs/<공고>/<날짜> 로 한 단계 더 들어간다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            snap = vault / "library" / "jobs" / "어떤회사 - 어떤직무"
            snap.mkdir(parents=True)
            (snap / "2026-08-15.md").write_text("원문\n", encoding="utf-8")
            self.assertIsNotNone(
                WV.resolve_page(vault, "library/jobs/어떤회사 - 어떤직무/2026-08-15"))

    def test_nested_path_did_not_open_traversal(self) -> None:
        """구분자를 허용해도 세그먼트 검사와 폴더 화이트리스트가 남아야 한다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (Path(d) / "secret.md").write_text("비밀\n", encoding="utf-8")
            for bad in ("library/../../secret", "library/jobs/../../../secret",
                        "etc/passwd", "../secret", "library//secret"):
                self.assertIsNone(WV.resolve_page(vault, bad), bad)

    def test_name_with_comma_or_parens_resolves(self) -> None:
        """쉼표와 괄호를 막으면 그 노트만 조용히 404 가 된다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            for stem in ("어떤회사 - 직무, 세부", "어떤회사 (지사)"):
                (vault / "library" / f"{stem}.md").write_text("x\n", encoding="utf-8")
                self.assertIsNotNone(WV.resolve_page(vault, stem), stem)

    def test_aliased_wikilink_becomes_a_link(self) -> None:
        """[[경로|표시]] 를 못 잡으면 원문 그대로 화면에 남는다."""
        out = WV.markdown("- [[library/jobs/A - B/2026-08-15|수집 2026-08-15]]\n")
        self.assertIn('href="/page/library/jobs/A%20-%20B/2026-08-15"', out)
        self.assertIn(">수집 2026-08-15</a>", out)
        self.assertNotIn("[[", out)

    def test_backslash_escapes_are_unwrapped(self) -> None:
        """defuddle 본문은 마크다운 특수문자를 이스케이프해서 넘어온다."""
        out = WV.markdown("Booking Holdings \\[NASDAQ: BKNG\\]\n")
        self.assertIn("[NASDAQ: BKNG]", out)
        self.assertNotIn("\\[", out)

    def test_triple_asterisk_is_bold_italic(self) -> None:
        out = WV.markdown("***방콕 근무***\n")
        self.assertIn("<b><i>방콕 근무</i></b>", out)
        self.assertNotIn("*", out)

    def test_folder_page_links_every_note(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            body = WV._folder_html(vault, "rest")
            self.assertIn("쉴 때 할 것", body)
            self.assertIn("아스테로이드 시티", body)
            self.assertIn("할 것", body)          # status 를 사람 말로 보여준다
            self.assertIn("%20", body)            # 공백이 URL 로 인코딩된다

    def test_folder_page_says_empty_instead_of_failing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "bare"
            (vault / "projects").mkdir(parents=True)
            self.assertIn("없음", WV._folder_html(vault, "rest"))

    def test_status_screen_keeps_leisure_off_the_front_page(self) -> None:
        """메인은 작업 상태를 보는 곳이다. 볼거리가 섞이면 성격이 흐려진다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            cfg = CFG.Config({})
            home = Path(d) / "home"
            home.mkdir()
            body = WV._status_html(home, vault, cfg)
            self.assertNotIn("아스테로이드 시티", body)
            self.assertNotIn("쉴 때 할 것", body)

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (Path(d) / "secret.md").write_text("비밀\n", encoding="utf-8")
            for bad in ("../secret", "../../etc/passwd", "..", "/etc/passwd"):
                self.assertIsNone(WV.resolve_page(vault, bad), bad)

    def test_rejects_dotfiles_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            for bad in ("", ".hidden", ".obsidian/app"):
                self.assertIsNone(WV.resolve_page(vault, bad), bad)

    def test_symlink_out_of_vault_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            outside = Path(d) / "outside.md"
            outside.write_text("바깥\n", encoding="utf-8")
            (vault / "projects" / "escape.md").symlink_to(outside)
            self.assertIsNone(WV.resolve_page(vault, "escape"))


class MarkdownTest(unittest.TestCase):
    def test_escapes_html_in_content(self) -> None:
        out = WV.markdown("- <script>alert(1)</script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_renders_headings_lists_and_tables(self) -> None:
        out = WV.markdown("## 제목\n\n- 항목\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
        self.assertIn("<h3>제목</h3>", out)
        self.assertIn("<li>항목</li>", out)
        self.assertIn("<th>a</th>", out)
        self.assertIn("<td>1</td>", out)

    def test_code_fence_preserves_layout(self) -> None:
        """계산식·다이어그램이 문단으로 흩어지면 공백 정렬이 전부 무너진다."""
        out = WV.markdown("앞\n\n```\n a  b\n ┌──┴──┐\n```\n\n뒤")
        self.assertIn("<pre><code>", out)
        self.assertIn(" a  b\n ┌──┴──┐", out)
        self.assertNotIn("<p> a  b</p>", out)

    def test_markdown_inside_a_fence_is_not_interpreted(self) -> None:
        out = WV.markdown("```\n# 제목이 아니다\n- 목록도 아니다\n| 표 | 도 |\n```")
        self.assertNotIn("<h2>", out)
        self.assertNotIn("<li>", out)
        self.assertNotIn("<table>", out)
        self.assertIn("# 제목이 아니다", out)

    def test_fence_content_is_html_escaped(self) -> None:
        out = WV.markdown("```\n<script>alert(1)</script>\n```")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_unclosed_fence_does_not_swallow_content(self) -> None:
        """내용이 조용히 사라지는 것이 최악이다."""
        out = WV.markdown("앞\n\n```\n안 닫힌 블록")
        self.assertIn("안 닫힌 블록", out)

    def test_fence_with_a_language_tag_still_closes(self) -> None:
        out = WV.markdown("```bash\necho hi\n```\n\n뒤 문단")
        self.assertIn("echo hi", out)
        self.assertIn("<p>뒤 문단</p>", out)

    def test_obsidian_embed_does_not_leave_a_broken_link(self) -> None:
        """![[x]] 는 옵시디언 전용이다. 그냥 두면 '!' 만 남고 링크가 404 가 된다."""
        out = WV.markdown("![[tasks.base]]")
        self.assertNotIn('href="/page/tasks.base"', out)
        self.assertNotIn("!<a", out)
        self.assertIn("옵시디언", out)
        self.assertIn("tasks.base", out)

    def test_plain_wikilink_still_links_next_to_an_embed(self) -> None:
        out = WV.markdown("![[tasks.base]]\n\n[[투자 심리]]")
        self.assertIn('href="/page/%ED%88%AC%EC%9E%90%20%EC%8B%AC%EB%A6%AC"', out)

    def test_external_markdown_link_becomes_an_anchor(self) -> None:
        out = WV.markdown("[국세청](https://www.nts.go.kr/a) 참고")
        self.assertIn('href="https://www.nts.go.kr/a"', out)
        self.assertIn(">국세청</a>", out)
        self.assertNotIn("](", out)

    def test_external_link_opens_in_a_new_tab_safely(self) -> None:
        out = WV.markdown("[x](https://example.com)")
        self.assertIn('target="_blank"', out)
        self.assertIn('rel="noopener noreferrer"', out)

    def test_query_string_ampersand_survives(self) -> None:
        """국세청 URL 이 mi=..&cntntsId=.. 형태다. 엔티티로 남아야 맞다."""
        out = WV.markdown("[a](https://www.nts.go.kr/x?mi=2515&cntntsId=7821)")
        self.assertIn("mi=2515&amp;cntntsId=7821", out)

    def test_javascript_scheme_is_not_linkified(self) -> None:
        out = WV.markdown("[클릭](javascript:alert(1))")
        self.assertNotIn("<a href=\"javascript:", out)
        self.assertNotIn("javascript:alert(1)\"", out)

    def test_link_text_cannot_break_out_of_the_attribute(self) -> None:
        out = WV.markdown('[x](https://e.com/"onmouseover="alert(1))')
        self.assertNotIn('onmouseover="alert', out)

    def test_wikilink_is_not_eaten_by_the_external_pattern(self) -> None:
        out = WV.markdown("[[투자 심리]] 와 [국세청](https://nts.go.kr)")
        self.assertIn('href="/page/%ED%88%AC%EC%9E%90%20%EC%8B%AC%EB%A6%AC"', out)
        self.assertIn('href="https://nts.go.kr"', out)

    def test_wikilink_with_a_space_is_url_encoded(self) -> None:
        """href 에 날 공백이 들어가면 URL 로 부정확하다. 표시 텍스트는 그대로 둔다."""
        out = WV.markdown("[[투자 심리]] 참고")
        self.assertIn('href="/page/%ED%88%AC%EC%9E%90%20%EC%8B%AC%EB%A6%AC"', out)
        self.assertIn(">투자 심리</a>", out)

    def test_wikilinks_become_internal_links(self) -> None:
        self.assertIn('href="/page/T-0043"', WV.markdown("- [[T-0043]] 제목"))

    def test_gen_markers_are_hidden(self) -> None:
        self.assertNotIn("GEN", WV.markdown("<!-- GEN:progress -->\n본문\n<!-- /GEN:progress -->"))


if __name__ == "__main__":
    unittest.main()
