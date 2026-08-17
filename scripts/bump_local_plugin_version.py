#!/usr/bin/env python3
"""Bump the patch version of the local plugin manifests by one.

Even when the marketplace is a directory source, Claude Code keeps and reads an
install-time copy in the cache, and cache invalidation happens only through the
version in plugin.json. Edit skill content while leaving the version alone and
update answers "already up to date" while the cache stays stale forever.

Measured: the cache was 27 days old and 2 of the 19 skills were missing from it
entirely.

The version is written in three places: the two plugin manifests
(.claude-plugin, .codex-plugin) and the marketplace entry at the repo root. If
the three diverge, skills.sh fails with manifest version drift. Bump them all
at once.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: bump_local_plugin_version.py <plugin-dir>", file=sys.stderr)
        return 2
    plugin_dir = Path(sys.argv[1])
    repo_root = plugin_dir.parent.parent
    plugin_name = plugin_dir.name
    manifests = [
        plugin_dir / ".claude-plugin" / "plugin.json",
        plugin_dir / ".codex-plugin" / "plugin.json",
    ]
    present = [m for m in manifests if m.is_file()]
    if not present:
        print(f"no plugin manifest under {plugin_dir}", file=sys.stderr)
        return 1
    marketplace = repo_root / ".claude-plugin" / "marketplace.json"

    parts = str(json.loads(present[0].read_text()).get("version", "0.0.0")).split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[2] = str(int(parts[2]) + 1)
    except ValueError:
        print(f"unparseable patch component: {parts[2]}", file=sys.stderr)
        return 1
    version = ".".join(parts[:3])

    for path in present:
        data = json.loads(path.read_text())
        data["version"] = version
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    # Bump the marketplace entry along with them. Miss it and skills.sh fails
    # with manifest version drift, a failure whose symptoms differ from the
    # cache problem and is easy to mistake for something else.
    if marketplace.is_file():
        data = json.loads(marketplace.read_text())
        touched = False
        for entry in data.get("plugins", []):
            if entry.get("name") == plugin_name and entry.get("version") != version:
                entry["version"] = version
                touched = True
        if touched:
            marketplace.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
