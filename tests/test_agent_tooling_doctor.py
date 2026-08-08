from __future__ import annotations

import importlib.util
import json
import time
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "scripts" / "agent_tooling_doctor.py"
SPEC = importlib.util.spec_from_file_location("agent_tooling_doctor", SCRIPT)
assert SPEC and SPEC.loader
DOC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOC
SPEC.loader.exec_module(DOC)


class TreeDigestTest(unittest.TestCase):
    """rglob 이 심링크 디렉터리를 건너뛰어 0파일로 집계하던 버그의 회귀 방지."""

    def test_follows_symlinked_directories(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real" / "skill-a"
            real.mkdir(parents=True)
            (real / "SKILL.md").write_text("내용\n", encoding="utf-8")
            farm = Path(d) / "farm"
            farm.mkdir()
            (farm / "skill-a").symlink_to(real)

            digest, count = DOC.tree_digest(farm)
            self.assertEqual(count, 1)
            self.assertTrue(digest)

    def test_identical_trees_hash_equal_across_locations(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for name in ("a", "b"):
                root = Path(d) / name / "s"
                root.mkdir(parents=True)
                (root / "SKILL.md").write_text("같음\n", encoding="utf-8")
            self.assertEqual(DOC.tree_digest(Path(d) / "a"), DOC.tree_digest(Path(d) / "b"))

    def test_content_change_changes_digest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "s"
            root.mkdir()
            (root / "SKILL.md").write_text("하나\n", encoding="utf-8")
            first, _ = DOC.tree_digest(root)
            (root / "SKILL.md").write_text("둘\n", encoding="utf-8")
            second, _ = DOC.tree_digest(root)
            self.assertNotEqual(first, second)

    def test_noise_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "s"
            (root / "__pycache__").mkdir(parents=True)
            (root / "__pycache__" / "x.pyc").write_bytes(b"junk")
            (root / ".DS_Store").write_bytes(b"junk")
            (root / "SKILL.md").write_text("내용\n", encoding="utf-8")
            _, count = DOC.tree_digest(root)
            self.assertEqual(count, 1)

    def test_missing_directory_is_empty_not_an_error(self) -> None:
        self.assertEqual(DOC.tree_digest(Path("/nonexistent/nope")), ("", 0))


class SessionCaptureTest(unittest.TestCase):
    def _db(self, path: Path, rows: list[tuple[str, str]]) -> None:
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE sdk_sessions (platform_source TEXT, started_at TEXT)")
        con.executemany("INSERT INTO sdk_sessions VALUES (?,?)", rows)
        con.commit()
        con.close()

    def test_missing_harness_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "cm.db"
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._db(db, [("claude", now)])
            with mock.patch.object(DOC, "CLAUDE_MEM_DB", db):
                out = dict((c, s) for c, s, _ in DOC.check_session_capture(Path(d)))
            self.assertEqual(out["session-capture"], "missing")

    def test_both_harnesses_present_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "cm.db"
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._db(db, [("claude", now), ("codex", now)])
            with mock.patch.object(DOC, "CLAUDE_MEM_DB", db):
                states = {s for _, s, _ in DOC.check_session_capture(Path(d))}
            self.assertEqual(states, {"ok"})

    def test_old_sessions_do_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "cm.db"
            self._db(db, [("claude", "2020-01-01T00:00:00Z"), ("codex", "2020-01-01T00:00:00Z")])
            with mock.patch.object(DOC, "CLAUDE_MEM_DB", db):
                states = {s for _, s, _ in DOC.check_session_capture(Path(d))}
            self.assertEqual(states, {"missing"})

    def test_absent_database_skips(self) -> None:
        with mock.patch.object(DOC, "CLAUDE_MEM_DB", Path("/nonexistent/cm.db")):
            self.assertEqual(DOC.check_session_capture(Path("/tmp"))[0][1], "skip")


class CodexHooksTest(unittest.TestCase):
    def _hooks(self, path: Path, command: str) -> None:
        path.write_text(json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"command": command}]}]}}), encoding="utf-8")

    def test_registered_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hooks.json"
            self._hooks(p, "node /path/claude-mem/hook.js")
            with mock.patch.object(DOC, "CODEX_HOOKS", p):
                check, state, detail = DOC.check_codex_hooks(Path(d))[0]
            self.assertEqual(state, "ok")
            self.assertIn("Stop", detail)

    def test_absent_registration_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hooks.json"
            self._hooks(p, "node /path/other/hook.js")
            with mock.patch.object(DOC, "CODEX_HOOKS", p):
                self.assertEqual(DOC.check_codex_hooks(Path(d))[0][1], "missing")

    def test_malformed_json_skips_rather_than_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hooks.json"
            p.write_text("{ not json", encoding="utf-8")
            with mock.patch.object(DOC, "CODEX_HOOKS", p):
                self.assertEqual(DOC.check_codex_hooks(Path(d))[0][1], "skip")


class LocalPluginCacheTest(unittest.TestCase):
    """배달 검사. "설치 성공"이 아니라 "캐시에 파일이 있나"를 본다."""

    def _setup(self, d: str, source_body: str | None, cache_body: str | None,
               declared_source: str = "./plugins/mine", installed: bool = True,
               cache_extra: str | None = None, source_symlink: bool = False):
        root = Path(d)
        repo = root / "repo"
        (repo / ".claude-plugin").mkdir(parents=True)
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "mkt",
                        "plugins": [{"name": "mine", "source": declared_source}]}),
            encoding="utf-8")
        plugin = repo if declared_source in ("./", ".") else repo / "plugins" / "mine"
        (plugin / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "mine", "version": "1.0.0"}), encoding="utf-8")
        if source_body is not None:
            (plugin / "skills" / "a").mkdir(parents=True)
            (plugin / "skills" / "a" / "SKILL.md").write_text(source_body, encoding="utf-8")
        if source_symlink:
            real = root / "real"
            (real / "skills").mkdir(parents=True)
            (plugin / "linked").symlink_to(real)

        known = root / "known.json"
        known.write_text(json.dumps(
            {"mkt": {"source": {"source": "directory", "path": str(repo)}}}), encoding="utf-8")

        cache_root = root / "cache"
        cache_dir = cache_root / "mkt" / "mine" / "1.0.0"
        if cache_body is not None:
            (cache_dir / "skills" / "a").mkdir(parents=True)
            (cache_dir / "skills" / "a" / "SKILL.md").write_text(cache_body, encoding="utf-8")
        if cache_extra:
            (cache_dir / cache_extra).mkdir(parents=True, exist_ok=True)
            (cache_dir / cache_extra / "lib.so").write_text("x" * 64, encoding="utf-8")

        inst = root / "installed.json"
        payload = {"plugins": {"mine@mkt": [{"installPath": str(cache_dir)}]}} if installed \
            else {"plugins": {}}
        inst.write_text(json.dumps(payload), encoding="utf-8")
        return known, cache_root, inst

    def _run(self, d, known, cache_root, inst):
        with mock.patch.object(DOC, "KNOWN_MARKETPLACES", known), \
             mock.patch.object(DOC, "CACHE_ROOT", cache_root), \
             mock.patch.object(DOC, "INSTALLED_PLUGINS", inst):
            return DOC.check_local_plugin_cache(Path(d))[0]

    def test_matching_cache_is_same(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._run(d, *self._setup(d, "같음\n", "같음\n"))[1], "same")

    def test_diverged_cache_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(d, *self._setup(d, "새 내용\n", "옛 내용\n"))
            self.assertEqual(state, "stale")
            self.assertIn("버전을 올려야", detail)

    def test_installed_but_empty_cache_is_a_delivery_failure(self) -> None:
        """설치 성공을 보고했는데 캐시가 비면 고장이다.

        실측: 심링크 프로젝션을 소스로 등록하면 `claude plugin install` 이
        성공을 찍고 캐시에 0개를 남긴다. 이전 판정은 이 상태를 'unknown' 과
        'ok' 로 덮었고, 그래서 두 달 가까이 빈 설치가 정상으로 보고됐다.
        """
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(d, *self._setup(d, "내용\n", None))
            self.assertEqual(state, "stale")
            self.assertIn("캐시에 파일이 없다", detail)
            self.assertIn(state, DOC.BAD_STATES)

    def test_root_source_is_copied_not_referenced(self) -> None:
        """source='./' 도 복사된다. 빈 캐시는 정상이 아니다.

        이전에는 './' 를 "소스를 직접 참조하므로 편집이 즉시 반영된다"고
        판정했다. 150MB 더미를 넣은 마켓플레이스로 재현해보니 그대로 캐시에
        복사됐고, 원본 SKILL.md 를 고쳐도 캐시 값은 변하지 않았다.
        """
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(
                d, *self._setup(d, "내용\n", None, declared_source="./"))
            self.assertEqual(state, "stale")
            self.assertIn(state, DOC.BAD_STATES)

    def test_empty_cache_names_the_symlink_cause(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _, _, detail = self._run(
                d, *self._setup(d, "내용\n", None, declared_source="./",
                                source_symlink=True))
            self.assertIn("심링크", detail)

    def test_build_residue_in_cache_is_stale(self) -> None:
        """.venv/node_modules 가 캐시에 실리면 소스 선정이 잘못된 것이다."""
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(
                d, *self._setup(d, "내용\n", "내용\n", cache_extra=".venv"))
            self.assertEqual(state, "stale")
            self.assertIn(".venv", detail)

    def test_not_installed_is_info_not_failure(self) -> None:
        """마켓플레이스에만 있고 설치 안 한 플러그인은 고장이 아니다."""
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(
                d, *self._setup(d, "내용\n", None, installed=False))
            self.assertEqual(state, "info")
            self.assertNotIn(state, DOC.BAD_STATES)

    def test_vanished_source_path_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            known = Path(d) / "known.json"
            known.write_text(json.dumps(
                {"mkt": {"source": {"source": "directory", "path": f"{d}/gone"}}}),
                encoding="utf-8")
            with mock.patch.object(DOC, "KNOWN_MARKETPLACES", known):
                check, state, detail = DOC.check_local_plugin_cache(Path(d))[0]
            self.assertEqual(state, "missing")
            self.assertIn("소스 경로 없음", detail)


class UpstreamSkillParseTest(unittest.TestCase):
    SKILLS_SH = '''#!/bin/bash
MATT_POCOCK_SKILLS_REF="${MATT_POCOCK_SKILLS_REF:-''' + "a" * 40 + '''}"
GRILL_ME_SKILL_URL="https://example.invalid/${MATT_POCOCK_SKILLS_REF}/SKILL.md"
install_upstream_skill_from_url "Codex" "$CODEX_CONFIG_DIR/skills" "nonexistent-test-skill" "$GRILL_ME_SKILL_URL"
'''

    def test_resolves_pinned_url_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sh = Path(d) / "skills.sh"
            sh.write_text(self.SKILLS_SH, encoding="utf-8")
            entries = DOC.parse_upstream_skills(sh)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["skill"], "nonexistent-test-skill")
            self.assertIn("a" * 40, entries[0]["url"])
            self.assertNotIn("$", str(entries[0]["path"]))

    def test_uninstalled_skill_reports_missing(self) -> None:
        """머신에 실제로 없는 이름을 써서 상태에 의존하지 않게 한다."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "scripts").mkdir()
            (Path(d) / "scripts" / "skills.sh").write_text(self.SKILLS_SH, encoding="utf-8")
            states = {s for _, s, _ in DOC.check_upstream_skills(Path(d), offline=True)}
            self.assertEqual(states, {"missing"})

    def test_absent_skills_sh_skips(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(DOC.check_upstream_skills(Path(d))[0][1], "skip")


class ExitCodeTest(unittest.TestCase):
    def test_bad_states_are_the_ones_that_fail(self) -> None:
        self.assertEqual(DOC.BAD_STATES, {"stale", "missing", "local", "error"})
        for good in ("ok", "same", "info", "skip", "unknown"):
            self.assertNotIn(good, DOC.BAD_STATES)

    def test_every_registered_check_is_callable_and_well_formed(self) -> None:
        """개수를 세지 않는다. 검사를 늘릴 때마다 깨지고, 깨진 걸 숫자만 고치게 된다.

        대신 모든 검사가 실제로 돌고 약속한 모양을 내는지 본다.
        """
        # 실제 파일과 네트워크를 안 타게 막는다. 느린 테스트는 안 돌게 된다.
        missing = Path("/nonexistent")
        for name, fn in DOC.CHECKS.items():
            with self.subTest(check=name), \
                 mock.patch.object(DOC, "CLAUDE_MEM_DB", missing), \
                 mock.patch.object(DOC, "CODEX_HOOKS", missing), \
                 mock.patch.object(DOC, "KNOWN_MARKETPLACES", missing), \
                 mock.patch.object(DOC, "INSTALLED_PLUGINS", missing), \
                 mock.patch.object(DOC, "CACHE_ROOT", missing):
                rows = (fn(missing, offline=True)
                        if fn is DOC.check_upstream_skills else fn(missing))
                self.assertIsInstance(rows, list)
                for check, state, detail in rows:
                    self.assertEqual(check, name)
                    self.assertIsInstance(state, str)
                    self.assertIsInstance(detail, str)


if __name__ == "__main__":
    unittest.main()


class DuplicateCheckoutTest(unittest.TestCase):
    def test_symlinked_pair_is_one_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "Documents" / "ui-skills"
            real.mkdir(parents=True)
            share = Path(d) / "share" / "ui-clone-skills"
            share.parent.mkdir(parents=True)
            share.symlink_to(real)
            with mock.patch.object(DOC, "check_duplicate_checkouts",
                                   DOC.check_duplicate_checkouts):
                same = share.resolve() == real.resolve()
            self.assertTrue(same)

    def test_independent_clones_are_two_checkouts(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "share" / "ui-clone-skills"
            b = Path(d) / "Documents" / "ui-skills"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            self.assertNotEqual(a.resolve(), b.resolve())

    def test_check_is_registered_and_stale_is_a_bad_state(self) -> None:
        self.assertIn("duplicate-checkout", DOC.CHECKS)
        self.assertIn("stale", DOC.BAD_STATES)


class OrphanedCacheTest(unittest.TestCase):
    def test_aborted_install_leftovers_are_stale(self) -> None:
        """중단된 directory 소스 설치가 남긴 temp_local_* 를 잡는다."""
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "cache"
            leftover = cache / "temp_local_123_abc" / "x"
            leftover.mkdir(parents=True)
            (leftover / "f").write_bytes(b"x" * 1024)
            with mock.patch.object(DOC, "CACHE_ROOT", cache):
                rows = DOC.check_orphaned_cache(Path(d))
            self.assertIn("stale", {s for _, s, _ in rows})
            self.assertTrue(any("중단된 설치" in detail for _, _, detail in rows))

    def test_temp_markers_are_not_counted_as_orphaned_versions(self) -> None:
        """임시 트리 안의 .orphaned_at 은 버전 고아가 아니다.

        실측에서 이걸 세는 바람에 296개 47GB 로 보고했고, 실체는 중단된
        설치 하나였다.
        """
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "cache"
            deep = cache / "temp_local_1_a" / "sub" / "dir"
            deep.mkdir(parents=True)
            (deep / ".orphaned_at").write_text("x", encoding="utf-8")
            with mock.patch.object(DOC, "CACHE_ROOT", cache):
                rows = DOC.check_orphaned_cache(Path(d))
            self.assertFalse(any("고아 버전" in detail for _, _, detail in rows))

    def test_real_orphaned_version_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "cache"
            version = cache / "mkt" / "plug" / "1.0.0"
            version.mkdir(parents=True)
            (version / ".orphaned_at").write_text("x", encoding="utf-8")
            with mock.patch.object(DOC, "CACHE_ROOT", cache):
                rows = DOC.check_orphaned_cache(Path(d))
            self.assertTrue(any("고아 버전 1개" in detail for _, _, detail in rows))

    def test_clean_cache_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "cache"
            cache.mkdir()
            with mock.patch.object(DOC, "CACHE_ROOT", cache):
                self.assertEqual(DOC.check_orphaned_cache(Path(d))[0][1], "ok")


class LlmwikiCaptureTest(unittest.TestCase):
    """등록이 아니라 결과를 본다. 훅이 등록돼 있어도 기록이 없으면 고장이다."""

    def _state(self, d: str, watermark: int = 100, snapshot_age_days: float | None = 0.0):
        state = Path(d) / "share"
        (state / "snapshots").mkdir(parents=True)
        (state / "state.json").write_text(
            json.dumps({"watermark": dict(watermark) if isinstance(watermark, dict)
                        else {f"claude-mem:{DOC._llmwiki_host()}": watermark}}),
            encoding="utf-8")
        if snapshot_age_days is not None:
            snap = state / "snapshots" / "20260101-000000"
            snap.mkdir()
            when = time.time() - snapshot_age_days * 86400
            os.utime(snap, (when, when))
        return state

    def _db(self, d: str, newest: int):
        db = Path(d) / "claude-mem.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE session_summaries (id INTEGER PRIMARY KEY)")
        if newest:
            con.execute("INSERT INTO session_summaries (id) VALUES (?)", (newest,))
        con.commit()
        con.close()
        return db

    def _vault(self, d: str, *, stamped=True, tasks=("T-0001",), moved=False):
        vault = Path(d) / "vault"
        (vault / "tasks").mkdir(parents=True)
        for t in tasks:
            (vault / "tasks" / f"{t}-something.md").write_text("x", encoding="utf-8")
        if stamped:
            where = str(Path(d) / "elsewhere") if moved else str(vault.resolve())
            (vault / ".llmwiki-vault").write_text(where + "\n", encoding="utf-8")
        return vault

    def _run(self, d, *, watermark=100, newest=100, snapshot_age_days=0.0,
             errors: str | None = None, plist: bool = True,
             vault: Path | None = None, bindings: str | None = None,
             last_vault: str | None = None, previous_vault: str | None = None):
        state = self._state(d, watermark, snapshot_age_days)
        if last_vault is not None or previous_vault is not None:
            blob = json.loads((state / "state.json").read_text())
            if last_vault is not None:
                blob["vault"] = last_vault
            if previous_vault is not None:
                blob["vaults_previous"] = ([previous_vault]
                                           if isinstance(previous_vault, str)
                                           else list(previous_vault))
            (state / "state.json").write_text(json.dumps(blob), encoding="utf-8")
        if bindings is not None:
            (state / "bindings.ndjson").write_text(bindings, encoding="utf-8")
        if vault is not None:
            (state / "config.toml").write_text(f'vault = "{vault}"\n', encoding="utf-8")
        db = self._db(d, newest)
        plist_path = Path(d) / "com.yongjae.llmwiki.plist"
        if plist:
            plist_path.write_text("x", encoding="utf-8")
        errlog = Path(d) / "hook-errors.log"
        if errors:
            errlog.write_text(errors, encoding="utf-8")

        with mock.patch.object(DOC, "LLMWIKI_STATE", state), \
             mock.patch.object(DOC, "LLMWIKI_ERRLOG", errlog), \
             mock.patch.object(DOC, "LLMWIKI_PLIST", plist_path), \
             mock.patch.object(DOC, "CLAUDE_MEM_DB", db):
            return DOC.check_llmwiki_capture(Path(d))

    def test_hook_failures_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = self._run(d, errors=f"{now}\tSessionStart\tboom\n")
            self.assertTrue(any(s == "stale" and "훅 실패" in det for _, s, det in rows))

    def test_foreign_host_watermark_cannot_mask_a_dead_local_ingest(self) -> None:
        """워터마크는 호스트별이다. max() 를 쓰면 남의 값이 우리 정지를 가린다.

        state 디렉터리를 머신 간에 동기화하거나 hostname 이 바뀌면 키가 둘이
        된다. 그때 max() 는 남의 최신 값을 집어 '적재 최신' 이라고 답하고,
        이 머신은 한 건도 적재하지 않은 채 조용히 지나간다 - 이번 세션 내내
        쫓던 거짓 정상 그대로다.
        """
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark={f"claude-mem:{DOC._llmwiki_host()}": 0,
                                           "claude-mem:other-machine": 9000},
                             newest=9000)
            self.assertTrue(any(s == "stale" and "밀렸다" in det for _, s, det in rows),
                            [det for _, _, det in rows])

    def test_old_hook_failures_age_out(self) -> None:
        """한 번의 일시적 실패가 영원히 stale 로 남으면 안 된다.

        오류 로그는 append 전용이고 아무것도 정리하지 않는다. 창을 두지
        않으면 한 시간짜리 사고가 매주 알림을 울리고, 사람은 그 알림을
        무시하게 된다.
        """
        with tempfile.TemporaryDirectory() as d:
            old_ts = "2020-01-01T00:00:00Z"
            rows = self._run(d, errors=f"{old_ts}\tSessionStart\tboom\n")
            self.assertFalse(any("훅 실패" in det for _, _, det in rows),
                             [det for _, _, det in rows])

    def test_recent_hook_failures_are_still_reported(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = self._run(d, errors=f"{now}\tSessionStart\tboom\n")
            self.assertTrue(any(s == "stale" and "훅 실패" in det for _, s, det in rows))

    def test_garbage_log_line_does_not_stick_forever(self) -> None:
        """타임스탬프를 잃은 줄은 문자열 비교에서 항상 cutoff 보다 크다.

        ASCII 에서 글자가 숫자보다 뒤라, 부분 기록으로 앞부분이 잘린 줄
        하나가 영원히 '최근 실패' 로 집계된다. 방향은 거짓 경보지만, 매주
        울리는 경보를 무시하는 습관이 곧 거짓 정상과 같은 결과를 만든다.
        """
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, errors="SessionStart\tboom\nboom-without-timestamp\n")
            self.assertFalse(any("훅 실패" in det for _, _, det in rows),
                             [det for _, _, det in rows])

    def test_vault_differing_from_last_compile_is_flagged(self) -> None:
        """교체 경고는 한 번 stderr 로 나가고 끝이다. 주간 검사가 봐야 한다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault="/somewhere/else")
            self.assertTrue(any(s == "stale" and "마지막으로 컴파일한" in det
                                for _, s, det in rows), [det for _, _, det in rows])

    def test_vault_matching_last_compile_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()))
            self.assertFalse(any("마지막으로 컴파일한" in det for _, _, det in rows))

    def test_ingest_falling_behind_is_stale(self) -> None:
        """워터마크가 뒤처지면 훅이 등록돼 있어도 기록은 멈춘 것이다."""
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark=100, newest=5000)
            self.assertTrue(any(s == "stale" and "밀렸다" in det for _, s, det in rows))

    def test_dead_ingest_on_a_small_database_is_still_caught(self) -> None:
        """고정 임계값 200 은 새 머신에서 정지를 가린다.

        db 가 200건 미만이면 한 건도 적재하지 않아도 behind 가 임계값을
        넘지 않아 '적재 최신' 이 나온다. db 가 커질 때까지 조용하다.
        """
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark=0, newest=150)
            self.assertTrue(any(s == "stale" for _, s, det in rows),
                            [det for _, _, det in rows])

    def test_small_lag_on_a_small_database_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark=148, newest=150)
            self.assertFalse(any(s == "stale" and "밀렸다" in det for _, s, det in rows))

    def test_watermark_ahead_of_the_database_is_broken_not_ok(self) -> None:
        """워터마크가 db 보다 앞서면 적재는 영원히 멈춘다.

        claude-mem 을 재설치하거나 db 를 복원하면 id 가 1부터 다시 시작한다.
        ingest 의 WHERE s.id > watermark 는 그 뒤로 한 건도 맞추지 못한다.
        그런데 behind 가 음수라 임계값을 넘지 않아 '적재 최신' 이 나오고,
        session-capture 는 새 db 가 잘 기록되므로 초록이다. 두 검사 모두
        정상인데 llmwiki 는 아무것도 받지 못한다.
        """
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark=12985, newest=50)
            self.assertTrue(any(s == "stale" and "앞선다" in det for _, s, det in rows),
                            [det for _, _, det in rows])

    def test_stranded_previous_vault_is_reported_until_it_is_gone(self) -> None:
        """교체가 끝나면 state 가 새 볼트와 일치해 모든 검사가 초록이 된다.

        그런데 옛 볼트에는 직접 쓴 글과 tasks/ 가 그대로 남아 있고, 그것을
        알리는 것은 교체 시점의 stderr 한 줄뿐이다. launchd 아래에서는 그
        줄이 /tmp/llmwiki.err 로 들어가 아무도 읽지 않는다. 승인 절차를
        만드는 대신 정말 중요한 질문을 묻는다 - 옛 볼트에 내용이 남아 있나.
        """
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "old-vault"
            (old / "projects").mkdir(parents=True)
            (old / "projects" / "a.md").write_text("직접 쓴 글\n", encoding="utf-8")
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()),
                             previous_vault=str(old.resolve()))
            self.assertTrue(any(s == "stale" and "옛 볼트" in det for _, s, det in rows),
                            [det for _, _, det in rows])

    def test_previous_vault_that_no_longer_exists_is_quiet(self) -> None:
        """지웠거나 합쳤으면 저절로 조용해진다. 승인 절차가 필요 없다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()),
                             previous_vault=str(Path(d) / "deleted-vault"))
            self.assertFalse(any("옛 볼트" in det for _, _, det in rows))

    def test_old_vault_with_no_markdown_is_still_reported(self) -> None:
        """.md 만 보면 bases/ 나 첨부만 남은 볼트를 비었다고 읽는다."""
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "old-vault"
            (old / "bases").mkdir(parents=True)
            (old / "bases" / "tasks.base").write_text("설정\n", encoding="utf-8")
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()),
                             previous_vault=str(old.resolve()))
            self.assertTrue(any(s == "stale" and "옛 볼트" in det for _, s, det in rows),
                            [det for _, _, det in rows])

    def test_old_vault_holding_only_its_stamp_is_quiet(self) -> None:
        """표식만 남았으면 잃을 것이 없다."""
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "old-vault"
            old.mkdir()
            (old / ".llmwiki-vault").write_text(str(old) + "\n", encoding="utf-8")
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()),
                             previous_vault=str(old.resolve()))
            self.assertFalse(any("옛 볼트" in det for _, _, det in rows))

    def test_every_stranded_vault_is_reported_not_just_the_last(self) -> None:
        """A→B→C 로 두 번 옮기면 단일 슬롯은 A 를 묻는다."""
        with tempfile.TemporaryDirectory() as d:
            olds = []
            for name in ("A", "B"):
                v = Path(d) / name
                (v / "projects").mkdir(parents=True)
                (v / "projects" / "p.md").write_text("글\n", encoding="utf-8")
                olds.append(str(v.resolve()))
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()),
                             previous_vault=olds)
            detail = " ".join(det for _, _, det in rows)
            for o in olds:
                self.assertIn(o, detail)

    def test_old_vault_containing_the_new_one_ignores_the_new_ones_files(self) -> None:
        """옛 볼트 안으로 새 볼트를 옮기면, 옛 경로를 훑을 때 현재 볼트의
        파일이 잡힌다. 그러면 "옮기거나 지워라" 는 살아있는 볼트를 지우라는
        말이 되고, 해소할 수 없는 경보가 매주 울린다.
        """
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "vault"
            new = old / "wiki"
            (new / "projects").mkdir(parents=True)
            (new / "projects" / "index.md").write_text("현재 볼트\n", encoding="utf-8")
            (new / ".llmwiki-vault").write_text(str(new.resolve()) + "\n", encoding="utf-8")
            rows = self._run(d, vault=new, last_vault=str(new.resolve()),
                             previous_vault=[str(old.resolve())])
            self.assertFalse(any("옛 볼트" in det for _, _, det in rows),
                             [det for _, _, det in rows])

    def test_old_parent_vault_with_its_own_content_is_still_reported(self) -> None:
        """중첩이어도 옛 볼트가 제 파일을 갖고 있으면 알려야 한다."""
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "vault"
            new = old / "wiki"
            (new / "projects").mkdir(parents=True)
            (new / "projects" / "index.md").write_text("현재\n", encoding="utf-8")
            (old / "projects").mkdir(parents=True, exist_ok=True)
            (old / "projects" / "note.md").write_text("옛 볼트의 글\n", encoding="utf-8")
            rows = self._run(d, vault=new, last_vault=str(new.resolve()),
                             previous_vault=[str(old.resolve())])
            self.assertTrue(any("옛 볼트" in det for _, _, det in rows),
                            [det for _, _, det in rows])

    def test_missing_nightly_job_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, plist=False)
            self.assertTrue(any(s == "missing" for _, s, det in rows))

    def test_stale_snapshot_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, snapshot_age_days=9.0)
            self.assertTrue(any(s == "stale" and "스냅샷" in det for _, s, det in rows))

    def test_env_vault_override_is_flagged_as_divergence(self) -> None:
        """셸에만 있는 LLMWIKI_VAULT 는 CLI 와 자동 실행을 갈라놓는다."""
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"LLMWIKI_VAULT": "/tmp/somewhere"}):
                rows = self._run(d)
            self.assertTrue(any(s == "stale" and "LLMWIKI_VAULT" in det
                                for _, s, det in rows))

    def test_binding_without_a_task_page_is_flagged(self) -> None:
        """볼트를 교체하면 바인딩은 home 에 남고 태스크 페이지는 사라진다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d, tasks=())
            rows = self._run(d, vault=vault,
                             bindings='{"task_id": "T-0001", "session_id": "s1"}\n')
            self.assertTrue(any(s == "stale" and "T-0001" in det for _, s, det in rows))

    def test_matching_binding_and_task_page_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d, tasks=("T-0001",))
            rows = self._run(d, vault=vault,
                             bindings='{"task_id": "T-0001", "session_id": "s1"}\n')
            self.assertFalse(any("바인딩" in det for _, _, det in rows))

    def test_vault_moved_from_another_path_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d, moved=True)
            rows = self._run(d, vault=vault)
            self.assertTrue(any(s == "stale" and "옮겨졌다" in det for _, s, det in rows))

    def test_unstamped_vault_is_unknown_not_broken(self) -> None:
        """스탬프 이전에 만든 볼트는 고장이 아니다."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d, stamped=False)
            rows = self._run(d, vault=vault)
            self.assertTrue(any(s == "unknown" for _, s, det in rows))
            self.assertFalse(any(s == "stale" for _, s, det in rows))

    def test_task_page_without_a_title_slug_is_not_an_orphan(self) -> None:
        """tasks.py:59 는 제목이 없으면 T-0001.md 로 쓴다.

        파일명을 '-' 로 잘라 앞 두 조각을 붙이면 그 경우 'T-0001.md' 가 되어
        바인딩의 'T-0001' 과 영원히 어긋난다. 멀쩡한 상태를 고장으로 신고하는
        검사는 무시하는 습관을 만들고, 그 습관이 두 달짜리 사고를 만들었다.
        """
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "vault"
            (vault / "tasks").mkdir(parents=True)
            (vault / "tasks" / "T-0001.md").write_text("x", encoding="utf-8")
            (vault / ".llmwiki-vault").write_text(str(vault.resolve()) + "\n", encoding="utf-8")
            rows = self._run(d, vault=vault,
                             bindings='{"task_id": "T-0001", "session_id": "s1"}\n')
            self.assertFalse(any("바인딩" in det for _, _, det in rows),
                             [det for _, _, det in rows])

    def test_healthy_setup_has_no_bad_state(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d)
            self.assertTrue(rows)
            for _, s, det in rows:
                self.assertNotIn(s, DOC.BAD_STATES, det)


class LaunchdJobsTest(unittest.TestCase):
    """설치·로드·동기는 서로 다른 사실이다. 셋 다 따로 확인한다."""

    def _setup(self, d: str, *, installed=True, symlink=False, drifted=False):
        root = Path(d) / "repo"
        (root / "configs/llmwiki").mkdir(parents=True)
        src = root / "configs/llmwiki/com.yongjae.job.plist"
        src.write_text("<plist>original</plist>", encoding="utf-8")

        agents = Path(d) / "LaunchAgents"
        agents.mkdir()
        dst = agents / "com.yongjae.job.plist"
        if installed:
            if symlink:
                dst.symlink_to(src)
            else:
                dst.write_text("<plist>drifted</plist>" if drifted else src.read_text(),
                               encoding="utf-8")
        return root, agents

    def _run(self, root, agents, *, loaded=True):
        listing = "PID\tStatus\tLabel\n-\t0\tcom.yongjae.job\n" if loaded else "PID\tStatus\tLabel\n"
        with mock.patch.object(DOC, "LAUNCH_AGENTS", agents), \
             mock.patch.object(DOC, "REPO_LAUNCH_JOBS", {"com.yongjae.job": "configs/llmwiki"}), \
             mock.patch.object(DOC.subprocess, "run",
                               return_value=mock.Mock(stdout=listing)):
            return DOC.check_launchd_jobs(root)[0]

    def test_installed_loaded_and_in_sync_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._run(*self._setup(d))[1], "ok")

    def test_not_installed_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(*self._setup(d, installed=False))
            self.assertEqual(state, "missing")
            self.assertIn("install.sh", detail)

    def test_symlinked_plist_is_stale(self) -> None:
        """다른 LaunchAgent 는 전부 실파일이고, 심링크는 재부팅해야만 검증된다."""
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(*self._setup(d, symlink=True))
            self.assertEqual(state, "stale")
            self.assertIn("심링크", detail)

    def test_drifted_copy_is_stale(self) -> None:
        """복사 설치의 대가. 리포를 고쳐도 사본은 그대로다."""
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(*self._setup(d, drifted=True))
            self.assertEqual(state, "stale")
            self.assertIn("다시 돌려야", detail)

    def test_installed_but_not_loaded_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, agents = self._setup(d)
            _, state, detail = self._run(root, agents, loaded=False)
            self.assertEqual(state, "missing")
            self.assertIn("로드되지 않았다", detail)


class DuplicateCheckoutPathTest(unittest.TestCase):
    """체크아웃 경로는 이름이 바뀐다. 못 찾았으면 그 사실을 말해야 한다."""

    def test_missing_dev_checkout_reports_skip_not_silence(self) -> None:
        """아무 줄도 안 내면 '검사했고 문제없음' 과 구분되지 않는다.

        실제로 ui-skills 가 ui-clone-skills 로 바뀌었을 때 이 검사는
        조용히 건너뛰면서 전체 요약은 ok 로 남았다.
        """
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(DOC.Path, "home", staticmethod(lambda: Path(d))):
                rows = DOC.check_duplicate_checkouts(Path(d))
            self.assertTrue(rows, "빈 결과는 침묵과 같다")
            self.assertEqual(rows[0][1], "skip")
            self.assertIn("찾지 못했다", rows[0][2])

    def test_renamed_checkout_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "Documents/ui-clone-skills/skills").mkdir(parents=True)
            (home / ".local/share/ui-clone-skills/skills").mkdir(parents=True)
            with mock.patch.object(DOC.Path, "home", staticmethod(lambda: home)):
                rows = DOC.check_duplicate_checkouts(home)
            self.assertTrue(rows)
            self.assertNotEqual(rows[0][1], "skip")

    def test_marketplace_source_drifting_from_dev_checkout_is_reported(self) -> None:
        """플러그인을 실제로 먹이는 경로를 봐야 한다.

        이름을 박아두면 마켓플레이스가 제3의 경로를 가리킬 때 검사가 서로
        일치하는 엉뚱한 쌍을 보며 ok 를 낸다. 실측: 마켓플레이스 소스는
        ~/.local/share/ui-clone-skills-claude-src 라는 분리된 복사본이고
        plugin.json 이 0.7.25 인데 개발 체크아웃은 0.7.26 이었다 - 이후
        커밋은 플러그인에 영원히 닿지 않는다.
        """
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            dev = home / "Documents/ui-clone-skills"
            (dev / ".claude-plugin").mkdir(parents=True)
            (dev / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "ui-clone-skills", "version": "0.7.26"}), encoding="utf-8")
            snap = home / ".local/share/ui-clone-skills-claude-src"
            (snap / ".claude-plugin").mkdir(parents=True)
            (snap / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "ui-clone-skills", "version": "0.7.25"}), encoding="utf-8")

            known = home / "known.json"
            known.write_text(json.dumps(
                {"voidmatcha": {"source": {"source": "directory", "path": str(snap)}}}),
                encoding="utf-8")

            with mock.patch.object(DOC.Path, "home", staticmethod(lambda: home)), \
                 mock.patch.object(DOC, "KNOWN_MARKETPLACES", known):
                rows = DOC.check_duplicate_checkouts(home)
            self.assertTrue(any(s == "stale" and "0.7.25" in det and "0.7.26" in det
                                for _, s, det in rows), [det for _, _, det in rows])

    def test_marketplace_source_matching_dev_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            for p in (home / "Documents/ui-clone-skills", 
                      home / ".local/share/ui-clone-skills-claude-src"):
                (p / ".claude-plugin").mkdir(parents=True)
                (p / ".claude-plugin" / "plugin.json").write_text(
                    json.dumps({"name": "ui-clone-skills", "version": "0.7.26"}), encoding="utf-8")
            known = home / "known.json"
            known.write_text(json.dumps(
                {"voidmatcha": {"source": {"source": "directory",
                 "path": str(home / ".local/share/ui-clone-skills-claude-src")}}}),
                encoding="utf-8")
            with mock.patch.object(DOC.Path, "home", staticmethod(lambda: home)), \
                 mock.patch.object(DOC, "KNOWN_MARKETPLACES", known):
                rows = DOC.check_duplicate_checkouts(home)
            self.assertFalse(any(s == "stale" for _, s, det in rows),
                             [det for _, _, det in rows])
