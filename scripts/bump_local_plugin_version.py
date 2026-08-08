#!/usr/bin/env python3
"""로컬 플러그인 매니페스트의 patch 버전을 하나 올린다.

Claude Code 는 마켓플레이스가 directory 소스여도 설치 시점 사본을 캐시에 두고
읽으며, 캐시 무효화는 plugin.json 의 version 으로만 일어난다. 스킬 내용만 고치고
버전을 그대로 두면 update 가 "이미 최신"이라 답하고 캐시는 영원히 묵는다.

실측: 캐시가 27일 묵어 있었고 스킬 19개 중 2개가 캐시에 아예 없었다.

버전은 세 곳에 적혀 있다: 플러그인 매니페스트 둘(.claude-plugin, .codex-plugin)과
저장소 루트의 마켓플레이스 항목. 셋이 갈라지면 skills.sh 가 manifest version
drift 로 실패한다. 한 번에 같이 올린다.
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

    # 마켓플레이스 항목도 같이 올린다. 빠뜨리면 skills.sh 가 manifest version
    # drift 로 실패하는데, 그 실패는 캐시 문제와 증상이 달라 헷갈리기 쉽다.
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
