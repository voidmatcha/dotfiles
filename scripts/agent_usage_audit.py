#!/usr/bin/env python3
"""Summarize local agent/skill install and usage signals without dumping transcripts."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

HOME = Path.home()
REPO = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]


def rel(path: Path) -> str:
    try:
        return "~" + str(path.expanduser()).removeprefix(str(HOME))
    except Exception:
        return str(path)


def exists_marker(path: Path) -> str:
    return "OK" if path.exists() or path.is_symlink() else "MISSING"


def local_agent_names() -> list[str]:
    names = []
    for path in sorted((REPO / "configs/agents").glob("*.md")):
        names.append(path.stem)
    return names


def local_skill_names() -> list[str]:
    names = []
    skills_root = REPO / "plugins/local-skills/skills"
    for path in sorted(skills_root.glob("*/SKILL.md")):
        names.append(path.parent.name)
    return names


def scan_usage(names: list[str]) -> tuple[int, Counter[str], Counter[str]]:
    projects = HOME / ".claude/projects"
    name_hits: Counter[str] = Counter()
    path_hits: Counter[str] = Counter()
    if not projects.exists():
        return 0, name_hits, path_hits

    files = sorted(projects.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
    patterns = {name: re.compile(rf"(?i)(?<![\w-]){re.escape(name)}(?![\w-])") for name in names}
    max_bytes = 2_000_000
    for path in files:
        try:
            text = path.open("rb").read(max_bytes).decode("utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in patterns.items():
            count = len(pattern.findall(text))
            if count:
                name_hits[name] += count
                path_hits[rel(path)] += count
        if "subagents/" in text:
            name_hits["subagents/"] += text.count("subagents/")
    return len(files), name_hits, path_hits


def main() -> int:
    agents = local_agent_names()
    skills = local_skill_names()
    names = agents + skills + ["orchestrate"]
    scanned, name_hits, path_hits = scan_usage(names)

    print("# Agent Usage Audit")
    print(f"Repo: {REPO}")
    print("\n## Local assets")
    for name in agents:
        print(f"- agent {name}: {exists_marker(HOME / '.claude/agents' / (name + '.md'))} {rel(HOME / '.claude/agents' / (name + '.md'))}")
    print(f"- command orchestrate: {exists_marker(HOME / '.claude/commands/orchestrate.md')} {rel(HOME / '.claude/commands/orchestrate.md')}")
    for name in skills:
        print(f"- codex skill {name}: {exists_marker(HOME / '.codex/skills' / name)} {rel(HOME / '.codex/skills' / name)}")

    print("\n## Recent usage signals")
    print(f"- searched Claude project logs: {scanned} file(s)")
    if not name_hits:
        print("- no local agent/skill name hits found in scanned logs")
    else:
        for name, count in name_hits.most_common(20):
            print(f"- {name}: {count}")

    if path_hits:
        print("\n## Top matching log paths")
        for path, count in path_hits.most_common(10):
            print(f"- {path}: {count}")

    print("\n## Interpretation guard")
    print("Counts are weak signals from the newest 50 logs and first 2 MB per file: they prove references, not successful task outcomes. Use them to prioritize follow-up checks, not as the sole install/prune decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
