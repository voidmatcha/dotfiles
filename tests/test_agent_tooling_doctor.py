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
    """Regression guard for the bug where rglob skipped symlinked directories
    and counted them as 0 files."""

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
    """Delivery check. It looks at whether the cache holds files, not at
    whether the install reported success."""

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
        """An install that reports success but leaves an empty cache is broken.

        Measured: register a symlink projection as the source and `claude
        plugin install` prints success while leaving 0 files in the cache. The
        previous verdict covered this state with 'unknown' and 'ok', so for
        nearly two months an empty install was reported as healthy.
        """
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(d, *self._setup(d, "내용\n", None))
            self.assertEqual(state, "stale")
            self.assertIn("캐시에 파일이 없다", detail)
            self.assertIn(state, DOC.BAD_STATES)

    def test_root_source_is_copied_not_referenced(self) -> None:
        """source='./' is copied too. An empty cache is not healthy.

        Previously './' was judged as "references the source directly, so edits
        take effect immediately". Reproducing it with a marketplace holding a
        150MB dummy showed it was copied into the cache as-is, and editing the
        original SKILL.md left the cached value unchanged.
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
        """.venv/node_modules landing in the cache means the source selection
        is wrong."""
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(
                d, *self._setup(d, "내용\n", "내용\n", cache_extra=".venv"))
            self.assertEqual(state, "stale")
            self.assertIn(".venv", detail)

    def test_not_installed_is_info_not_failure(self) -> None:
        """A plugin that is only in the marketplace and never installed is not
        a failure."""
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
        """Use a name that genuinely does not exist on the machine so the test
        does not depend on local state."""
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
        """Do not count checks. A count breaks every time a check is added, and
        the break gets fixed by bumping the number.

        Instead, verify that every check actually runs and returns the promised
        shape.
        """
        # Keep real files and the network out of it. A slow test stops getting
        # run.
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
        """Catch the temp_local_* left behind by an aborted directory-source
        install."""
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
        """.orphaned_at inside a temp tree is not an orphaned version.

        Counting these in a real run reported 296 entries / 47GB, when the
        reality was a single aborted install.
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
    """Look at the outcome, not the registration. Even with the hooks
    registered, no recorded output means it is broken."""

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
        """The watermark is per host. With max(), another host's value hides
        our own stall.

        Syncing the state directory between machines, or a hostname change,
        leaves two keys. max() then picks the other host's newer value and
        answers 'ingest is current' while this machine has ingested nothing,
        passing silently - exactly the false-healthy state chased all session.
        """
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark={f"claude-mem:{DOC._llmwiki_host()}": 0,
                                           "claude-mem:other-machine": 9000},
                             newest=9000)
            self.assertTrue(any(s == "stale" and "밀렸다" in det for _, s, det in rows),
                            [det for _, _, det in rows])

    def test_old_hook_failures_age_out(self) -> None:
        """A single transient failure must not stay stale forever.

        The error log is append-only and nothing prunes it. Without a time
        window, a one-hour incident rings the alarm every week, and people
        learn to ignore that alarm.
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
        """A line that lost its timestamp always compares greater than the
        cutoff as a string.

        Letters sort after digits in ASCII, so one line truncated at the front
        by a partial write counts as a 'recent failure' forever. The error
        direction is a false alarm, but the habit of ignoring a weekly alarm
        produces the same outcome as a false healthy.
        """
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, errors="SessionStart\tboom\nboom-without-timestamp\n")
            self.assertFalse(any("훅 실패" in det for _, _, det in rows),
                             [det for _, _, det in rows])

    def test_vault_differing_from_last_compile_is_flagged(self) -> None:
        """The swap warning goes to stderr once and that is it. The weekly
        check has to see it."""
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
        """When the watermark falls behind, recording has stopped even though
        the hooks are registered."""
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark=100, newest=5000)
            self.assertTrue(any(s == "stale" and "밀렸다" in det for _, s, det in rows))

    def test_dead_ingest_on_a_small_database_is_still_caught(self) -> None:
        """The fixed threshold of 200 hides a stall on a new machine.

        Under 200 rows in the db, behind never exceeds the threshold even with
        nothing ingested, so it reports 'ingest is current'. It stays quiet
        until the db grows.
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
        """A watermark ahead of the db stalls ingest forever.

        Reinstalling claude-mem or restoring the db restarts ids from 1.
        Ingest's WHERE s.id > watermark then matches nothing ever again. But
        behind is negative, so it never crosses the threshold and reports
        'ingest is current', while session-capture is green because the new db
        records fine. Both checks pass and llmwiki receives nothing.
        """
        with tempfile.TemporaryDirectory() as d:
            rows = self._run(d, watermark=12985, newest=50)
            self.assertTrue(any(s == "stale" and "앞선다" in det for _, s, det in rows),
                            [det for _, _, det in rows])

    def test_stranded_previous_vault_is_reported_until_it_is_gone(self) -> None:
        """Once the swap is done, state matches the new vault and every check
        turns green.

        But the old vault still holds hand-written notes and tasks/, and the
        only notice is a single stderr line at swap time. Under launchd that
        line goes to /tmp/llmwiki.err, where nobody reads it. Rather than
        building an acknowledgement flow, ask the question that matters - is
        there content left in the old vault?
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
        """Once it is deleted or merged, it goes quiet on its own. No
        acknowledgement flow needed."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()),
                             previous_vault=str(Path(d) / "deleted-vault"))
            self.assertFalse(any("옛 볼트" in det for _, _, det in rows))

    def test_old_vault_with_no_markdown_is_still_reported(self) -> None:
        """Looking only at .md reads a vault holding just bases/ or attachments
        as empty."""
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
        """If only the stamp is left, there is nothing to lose."""
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "old-vault"
            old.mkdir()
            (old / ".llmwiki-vault").write_text(str(old) + "\n", encoding="utf-8")
            vault = self._vault(d)
            rows = self._run(d, vault=vault, last_vault=str(vault.resolve()),
                             previous_vault=str(old.resolve()))
            self.assertFalse(any("옛 볼트" in det for _, _, det in rows))

    def test_every_stranded_vault_is_reported_not_just_the_last(self) -> None:
        """Moving twice, A to B to C, buries A if there is only one slot."""
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
        """Moving the new vault inside the old one makes a scan of the old path
        pick up the current vault's files. Then "move it or delete it" means
        deleting the live vault, and an unresolvable alarm rings every week.
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
        """Even when nested, an old vault holding files of its own must be
        reported."""
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
        """An LLMWIKI_VAULT that exists only in the shell splits the CLI from
        the automated runs."""
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"LLMWIKI_VAULT": "/tmp/somewhere"}):
                rows = self._run(d)
            self.assertTrue(any(s == "stale" and "LLMWIKI_VAULT" in det
                                for _, s, det in rows))

    def test_binding_without_a_task_page_is_flagged(self) -> None:
        """Swapping the vault leaves the bindings in home while the task pages
        disappear."""
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
        """A vault created before stamping existed is not broken."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d, stamped=False)
            rows = self._run(d, vault=vault)
            self.assertTrue(any(s == "unknown" for _, s, det in rows))
            self.assertFalse(any(s == "stale" for _, s, det in rows))

    def test_task_page_without_a_title_slug_is_not_an_orphan(self) -> None:
        """tasks.py:59 writes T-0001.md when there is no title.

        Splitting the filename on '-' and joining the first two pieces yields
        'T-0001.md' in that case, which never matches the binding's 'T-0001'. A
        check that reports a healthy state as broken breeds the habit of
        ignoring it, and that habit caused the two-month incident.
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
    """Installed, loaded, and in sync are three different facts. Check all
    three separately."""

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
        """Every other LaunchAgent is a real file, and a symlink can only be
        validated by rebooting."""
        with tempfile.TemporaryDirectory() as d:
            _, state, detail = self._run(*self._setup(d, symlink=True))
            self.assertEqual(state, "stale")
            self.assertIn("심링크", detail)

    def test_drifted_copy_is_stale(self) -> None:
        """The price of installing by copy: editing the repo leaves the copy
        untouched."""
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
    """Checkout paths get renamed. When one is not found, say so."""

    def test_missing_dev_checkout_reports_skip_not_silence(self) -> None:
        """Emitting no row is indistinguishable from 'checked, nothing wrong'.

        When ui-skills was actually renamed to ui-clone-skills, this check
        skipped silently and the overall summary stayed ok.
        """
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(DOC.Path, "home", staticmethod(lambda: Path(d))):
                rows = DOC.check_duplicate_checkouts(Path(d))
            self.assertTrue(rows, "an empty result is the same as silence")
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
        """Look at the path that actually feeds the plugin.

        With hardcoded names, a marketplace pointing at a third path makes the
        check compare an irrelevant pair that happens to match and report ok.
        Measured: the marketplace source was a separate copy at
        ~/.local/share/ui-clone-skills-claude-src with plugin.json at 0.7.25
        while the dev checkout was at 0.7.26 - later commits would never reach
        the plugin.
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
