import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "prune_claude_plugin_cache.py"


def load_module():
    spec = importlib.util.spec_from_file_location("prune_claude_plugin_cache", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PruneClaudePluginCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def _version(self, root: Path, name: str, age_days: float, *, marker=True) -> Path:
        version = root / "marketplace" / name / "1.0.0"
        version.mkdir(parents=True)
        (version / "payload.bin").write_bytes(b"x" * 128)
        if marker:
            orphaned = version / ".orphaned_at"
            orphaned.touch()
            timestamp = time.time() - age_days * 86400
            os.utime(orphaned, (timestamp, timestamp))
        return version

    def test_prunes_only_old_exact_depth_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            old = self._version(root, "old", 8)
            fresh = self._version(root, "fresh", 1)
            active = self._version(root, "active", 30, marker=False)
            nested = root / "marketplace" / "nested" / "1.0.0" / "child"
            nested.mkdir(parents=True)
            (nested / ".orphaned_at").touch()

            result = self.module.prune(root, min_age_days=7)

            self.assertEqual(result.removed_count, 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(active.exists())
            self.assertTrue(nested.exists())

    def test_dry_run_reports_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            old = self._version(root, "old", 8)

            result = self.module.prune(root, min_age_days=7, dry_run=True)

            self.assertEqual(result.removed_count, 1)
            self.assertTrue(old.exists())

    def test_parent_symlink_cannot_escape_cache_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "cache"
            outside = base / "outside"
            old = self._version(outside, "old", 8)
            root.mkdir()
            (root / "marketplace").symlink_to(outside / "marketplace", target_is_directory=True)

            result = self.module.prune(root, min_age_days=7)

            self.assertEqual(result.removed_count, 0)
            self.assertTrue(old.exists())

    def test_symlinked_cache_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            outside = base / "outside"
            old = self._version(outside, "old", 8)
            root = base / "cache"
            root.symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                self.module.prune(root, min_age_days=7, dry_run=True)

            self.assertTrue(old.exists())

    def test_cli_rejects_symlinked_cache_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            outside = base / "outside"
            old = self._version(outside, "old", 8)
            root = base / ".claude" / "plugins" / "cache"
            root.parent.mkdir(parents=True)
            root.symlink_to(outside, target_is_directory=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--root",
                    str(root),
                    "--min-age-days",
                    "7",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr.lower())
            self.assertTrue(old.exists())


if __name__ == "__main__":
    unittest.main()
