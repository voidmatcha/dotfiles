#!/usr/bin/env python3
"""Find agent/skill assets that mention upstream sources without clear provenance."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATE_GLOBS = [
    "configs/agents/*.md",
    "configs/commands/*.md",
    "plugins/*/skills/*/SKILL.md",
    "plugins/*/.claude-plugin/plugin.json",
    "plugins/*/.codex-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
]
UPSTREAM_RE = re.compile(r"(?im)(^\s*(?:source|upstream):|adapted from|based on (?:https?|github|upstream)|inspired by|vendored from)")
LICENSE_RE = re.compile(r"(?i)(license|SPDX|MIT|Apache-2\.0|BSD|GPL|proprietary|unknown)")
MODE_RE = re.compile(r"(?i)(vendored|adapted|inspired-by|inspired by|original)")


def main() -> int:
    flagged: list[str] = []
    scanned = 0
    for glob in CANDIDATE_GLOBS:
        for path in sorted(REPO.glob(glob)):
            if not path.is_file():
                continue
            scanned += 1
            text = path.read_text(errors="ignore")
            if UPSTREAM_RE.search(text) and not (LICENSE_RE.search(text) and MODE_RE.search(text)):
                flagged.append(str(path.relative_to(REPO)))

    print("# Source Provenance Audit")
    print(f"Scanned: {scanned} asset file(s)")
    if not flagged:
        print("No likely provenance gaps found by heuristic scan.")
    else:
        print("Likely needs provenance note:")
        for path in flagged:
            print(f"- {path}")
        print("\nAdd near-file notes with Upstream, License, Mode, and Local changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
