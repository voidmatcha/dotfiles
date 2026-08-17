from __future__ import annotations

import importlib.util
import sys
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "llmwiki" / "config.py"
SPEC = importlib.util.spec_from_file_location("llmwiki_config", SCRIPT)
assert SPEC and SPEC.loader
CFG = importlib.util.module_from_spec(SPEC)
# dataclasses looks the module up in sys.modules while resolving
# field(default_factory=...), so it must be registered before exec_module.
# Without the registration this raises AttributeError.
sys.modules[SPEC.name] = CFG
SPEC.loader.exec_module(CFG)


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


class ConfigTest(unittest.TestCase):
    def test_defaults_apply_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = CFG.load(Path(d))
            self.assertEqual(c.active_threshold, 5)
            self.assertEqual(c.unclassified_days, 14)
            self.assertEqual(c.index_max_chars, 8000)
            self.assertEqual(c.archive_days, 180)
            self.assertEqual(c.stale_days, 7)
            self.assertEqual(c.blocklist, frozenset())
            self.assertEqual(c.mapping, {})

    @requires_tomllib

    def test_file_values_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text(
                'blocklist = ["yongjae", "Documents"]\n'
                "active_threshold = 9\n"
                "[mapping]\n"
                'llmwiki-wt1 = "llmwiki"\n',
                encoding="utf-8",
            )
            c = CFG.load(Path(d))
            self.assertEqual(c.blocklist, frozenset({"yongjae", "Documents"}))
            self.assertEqual(c.active_threshold, 9)
            self.assertEqual(c.mapping["llmwiki-wt1"], "llmwiki")
            self.assertEqual(c.unclassified_days, 14)

    @requires_tomllib

    def test_resolve_maps_then_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text(
                'blocklist = ["junk"]\n[mapping]\nraw = "junk"\n', encoding="utf-8"
            )
            c = CFG.load(Path(d))
            # Mapping comes first: raw -> junk -> blocked. Blocking does not
            # discard, it routes to unfiled, so the result is not None.
            self.assertEqual(c.resolve_project("raw"), CFG.UNFILED)
            self.assertEqual(c.resolve_project("keep"), "keep")


if __name__ == "__main__":
    unittest.main()


class VaultResolutionTest(unittest.TestCase):
    """The vault path must be decided in exactly one place.

    Change it with env alone and the CLI uses the new path while launchd
    and the hooks use the default one, because neither of those reads the
    shell rc. Confirmed by measurement - a compile run with LLMWIKI_VAULT
    set built an entire vault at the alternate path while the default
    vault stayed where it was. Nothing tells you they have diverged.
    """

    @requires_tomllib

    def test_config_key_decides_the_vault(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "config.toml").write_text('vault = "/tmp/from-config"\n', encoding="utf-8")
            self.assertEqual(CFG.vault(home), Path("/tmp/from-config"))

    @requires_tomllib

    def test_env_overrides_config_for_one_off_runs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "config.toml").write_text('vault = "/tmp/from-config"\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {"LLMWIKI_VAULT": "/tmp/from-env"}):
                self.assertEqual(CFG.vault(home), Path("/tmp/from-env"))

    def test_falls_back_to_default_without_config_or_env(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if k != "LLMWIKI_VAULT"}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(CFG.vault(Path(d)), Path.home() / "Documents/llmwiki")

    @requires_tomllib

    def test_tilde_in_config_is_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "config.toml").write_text('vault = "~/elsewhere/wiki"\n', encoding="utf-8")
            self.assertEqual(CFG.vault(home), Path.home() / "elsewhere/wiki")

    @requires_tomllib
    def test_relative_vault_is_anchored_to_home_not_cwd(self) -> None:
        """A relative path resolves to a different vault depending on cwd.

        compile runs from the checkout, doctor from wherever the user
        happens to be, and the hooks from somewhere else again. If the same
        setting resolves to different absolute paths, the vault splits and
        the checks raise false swap alarms. Anchor on the directory holding
        the config file - unlike cwd, that is the same wherever you run.
        """
        import os
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "state"
            home.mkdir()
            (home / "config.toml").write_text('vault = "wiki"\n', encoding="utf-8")
            here = os.getcwd()
            try:
                os.chdir(tempfile.gettempdir())
                first = CFG.vault(home)
            finally:
                os.chdir(here)
            second = CFG.vault(home)
            self.assertEqual(first, second)
            self.assertEqual(first, home / "wiki")
