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


LT, CFG, ST = _load("linter"), _load("config"), _load("store")


class LinterTest(unittest.TestCase):
    def _vault(self, d: str) -> Path:
        vault = Path(d) / "v"
        (vault / "tasks").mkdir(parents=True)
        (vault / "projects").mkdir(parents=True)
        (vault / "index.md").write_text("# index\n", encoding="utf-8")
        return vault

    def test_clean_vault_has_no_errors(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (vault / "tasks" / "T-0001.md").write_text(
                "---\ntype: task\nid: T-0001\nproject: p\nstatus: queued\n---\n\n## 목표\n",
                encoding="utf-8",
            )
            errors, _ = LT.run(Path(d) / "h", vault, CFG.Config())
            self.assertEqual(errors, [])

    def test_missing_required_key_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (vault / "tasks" / "T-0002.md").write_text(
                "---\ntype: task\nid: T-0002\n---\n\n## 목표\n", encoding="utf-8"
            )
            errors, _ = LT.run(Path(d) / "h", vault, CFG.Config())
            self.assertTrue(any("status" in e for e in errors))

    def test_damaged_marker_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (vault / "tasks" / "T-0003.md").write_text(
                "---\ntype: task\nid: T-0003\nproject: p\nstatus: queued\n---\n"
                "<!-- GEN:progress -->\n닫히지 않음\n",
                encoding="utf-8",
            )
            errors, _ = LT.run(Path(d) / "h", vault, CFG.Config())
            self.assertTrue(any("progress" in e for e in errors))

    def test_blocked_without_reason_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (vault / "tasks" / "T-0004.md").write_text(
                "---\ntype: task\nid: T-0004\nproject: p\nstatus: blocked\n"
                "blocked_by: \"\"\n---\n",
                encoding="utf-8",
            )
            errors, _ = LT.run(Path(d) / "h", vault, CFG.Config())
            self.assertTrue(any("blocked_by" in e for e in errors))

    def test_done_task_absent_from_index_is_not_an_orphan_warning(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault(d)
            (vault / "tasks" / "T-0005.md").write_text(
                "---\ntype: task\nid: T-0005\nproject: p\nstatus: done\n---\n",
                encoding="utf-8",
            )
            _, warnings = LT.run(Path(d) / "h", vault, CFG.Config())
            self.assertFalse(any("고아" in w for w in warnings))

    def test_dangling_binding_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", self._vault(d)
            ST.append_json(home / "bindings.ndjson", {
                "session_id": "s1", "task_id": "T-9999",
                "dismissed": False, "at": "2026-08-01T00:00:00Z",
            })
            _, warnings = LT.run(home, vault, CFG.Config())
            self.assertTrue(any("T-9999" in w for w in warnings))

    def test_broken_event_lines_are_warned(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", self._vault(d)
            home.mkdir(parents=True, exist_ok=True)
            (home / "events.ndjson").write_text('{"a": 1}\n{"trunc\n', encoding="utf-8")
            _, warnings = LT.run(home, vault, CFG.Config())
            self.assertTrue(any("깨진" in w for w in warnings))

    def test_zero_events_warns_that_automation_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _, warnings = LT.run(Path(d) / "h", self._vault(d), CFG.Config())
            self.assertTrue(any("자동화" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
