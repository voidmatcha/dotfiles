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


SC = _load("scaffold")


def _has_tomllib() -> bool:
    try:
        import tomllib  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


# Tests that actually parse config.toml cannot hold without tomllib (3.11+).
# It is correct for the code to fail loudly rather than fall back to defaults
# silently, so we skip here instead of weakening the assertions.
requires_tomllib = unittest.skipUnless(_has_tomllib(), "tomllib (python 3.11+) 필요")


class ScaffoldTest(unittest.TestCase):
    def test_init_creates_expected_layout(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault, home = Path(d) / "v", Path(d) / "h"
            SC.init(vault, home)
            for rel in ("index.md", "log.md", "dashboard.md", "bases/tasks.base"):
                self.assertTrue((vault / rel).exists(), rel)
            for folder in ("tasks", "projects"):
                self.assertTrue((vault / folder).is_dir())
            self.assertTrue((home / "config.toml").exists())

    def test_init_refuses_nonempty_vault_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault, home = Path(d) / "v", Path(d) / "h"
            vault.mkdir(parents=True)
            (vault / "already.md").write_text("x", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                SC.init(vault, home)
            SC.init(vault, home, force=True)
            self.assertTrue((vault / "index.md").exists())

    def test_seed_config_blocks_known_junk_projects(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault, home = Path(d) / "v", Path(d) / "h"
            SC.init(vault, home)
            text = (home / "config.toml").read_text(encoding="utf-8")
            for junk in ("yongjae", "Documents", "workspace", "tmp"):
                self.assertIn(junk, text)

    @requires_tomllib

    def test_seed_config_parses_as_toml_and_blocks(self) -> None:
        import tomllib
        with tempfile.TemporaryDirectory() as d:
            vault, home = Path(d) / "v", Path(d) / "h"
            SC.init(vault, home)
            with (home / "config.toml").open("rb") as fh:
                data = tomllib.load(fh)
            self.assertIn("yongjae", data["blocklist"])
            self.assertEqual(data["mapping"]["ui-skills/2026-06-22"], "ui-skills")

    def test_tasks_base_defines_three_views(self) -> None:
        self.assertEqual(SC.TASKS_BASE.count("- type:"), 3)
        self.assertIn("daysSinceModified", SC.TASKS_BASE)

    def test_init_does_not_overwrite_existing_base(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault, home = Path(d) / "v", Path(d) / "h"
            SC.init(vault, home)
            (vault / "bases" / "tasks.base").write_text("사람이 고침\n", encoding="utf-8")
            SC.init(vault, home, force=True)
            self.assertEqual(
                (vault / "bases" / "tasks.base").read_text(encoding="utf-8"), "사람이 고침\n"
            )


if __name__ == "__main__":
    unittest.main()


class ConfigGuardTest(unittest.TestCase):
    def test_compile_refuses_to_run_without_config(self) -> None:
        """With no config.toml there is no blocklist either, so junk pages
        get created."""
        import subprocess
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as d:
            home, vault = Path(d) / "h", Path(d) / "v"
            home.mkdir(parents=True)
            proc = subprocess.run(
                [sys.executable, "-m", "scripts.llmwiki", "compile"],
                capture_output=True, text=True, cwd=root,
                env={"PATH": "/usr/bin:/bin", "LLMWIKI_HOME": str(home),
                     "LLMWIKI_VAULT": str(vault), "HOME": str(Path(d))},
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("config.toml", proc.stderr)
