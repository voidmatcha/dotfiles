from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "source_provenance_audit.py"


class SourceProvenanceAuditTest(unittest.TestCase):
    def run_audit(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--root", str(root), "--format", "json", "--strict"],
            capture_output=True,
            text=True,
            check=False,
        )

    def write_skill(self, root: Path, text: str) -> None:
        skill = root / "plugins" / "demo" / "skills" / "imported" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(text, encoding="utf-8")

    def test_strict_mode_flags_adapted_asset_without_local_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_skill(
                root,
                """---
name: imported
description: imported fixture
---
Provenance: Upstream: https://example.test/upstream; License: MIT; Mode: adapted.
""",
            )
            completed = self.run_audit(root)

        self.assertEqual(completed.returncode, 1, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["gaps"][0]["missing"], ["local_changes"])

    def test_accepts_agent_skills_metadata_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_skill(
                root,
                """---
name: imported
description: imported fixture
license: MIT
compatibility: Requires public network access.
metadata:
  dotfiles.provenance.upstream: https://example.test/upstream
  dotfiles.provenance.mode: adapted
  dotfiles.provenance.local-changes: Rewritten for local safety boundaries.
---
# Imported
""",
            )
            completed = self.run_audit(root)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["gaps"], [])


if __name__ == "__main__":
    unittest.main()
