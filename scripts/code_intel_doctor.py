#!/usr/bin/env python3
"""Check local code intelligence wiring for codegraph/serena/MCP."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[1]
TARGET = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
HOME = Path.home()


def mark(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def has_toml_server(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = tomllib.loads(path.read_text())
    except Exception:
        return False
    return name in data.get("mcp_servers", {})


def has_json_server(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    return name in data.get("mcpServers", {})


def main() -> int:
    codex_cfg = REPO / "configs/codex/config.toml"
    claude_mcp = REPO / "configs/mcp.json"
    live_codex = HOME / ".codex/config.toml"

    print("# Code Intel Doctor")
    print(f"Target repo: {TARGET}")
    print("\n## Commands")
    for cmd in ("codegraph", "serena", "codex", "claude"):
        path = shutil.which(cmd)
        print(f"- {cmd}: {mark(bool(path))}{' ' + path if path else ''}")

    print("\n## Shared config")
    for server in ("codegraph", "serena"):
        print(f"- configs/codex config has {server}: {mark(has_toml_server(codex_cfg, server))}")
        print(f"- configs/mcp.json has {server}: {mark(has_json_server(claude_mcp, server))}")
        print(f"- live ~/.codex/config.toml has {server}: {mark(has_toml_server(live_codex, server))}")

    print("\n## Target repo indexes")
    print(f"- .codegraph directory: {mark((TARGET / '.codegraph').exists())}")
    print(f"- .serena directory: {mark((TARGET / '.serena').exists())}")
    print("\n## Next actions")
    if not (TARGET / ".codegraph").exists():
        print("- Run `codegraph init -i` in the target repo when graph tracing is needed.")
    if not (TARGET / ".serena").exists():
        print("- Activate the repo with serena once before relying on LSP edits.")
    print("- Re-run this doctor after setup and prefer codegraph for broad traces, serena for type-aware edits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
