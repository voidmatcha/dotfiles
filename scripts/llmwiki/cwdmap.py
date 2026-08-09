from __future__ import annotations

import importlib.util
import sys
from bisect import bisect_right
from pathlib import Path

_HERE = Path(__file__).parent


def _load(name: str):
    """이미 로드된 모듈은 재사용한다.

    캐시하지 않으면 상호 참조가 무한 재귀가 된다. compiler 가 queries 를,
    queries 가 compiler 를 부르는 구조에서 실제로 멈췄다.
    """
    key = f"llmwiki_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


store = _load("store")


def record(home: Path, session_id: str, cwd: str, at: str) -> bool:
    """cwd가 바뀐 시점만 남긴다. 훅이 매 프롬프트마다 불러도 파일이 안 자란다."""
    path = home / "cwd.ndjson"
    rows, _ = store.read_json(path)
    for row in reversed(rows):
        if row.get("session_id") == session_id:
            if row.get("cwd") == cwd:
                return False
            break
    store.append_json(path, {"session_id": session_id, "cwd": cwd, "at": at})
    return True


def build(home: Path) -> dict[str, list[tuple[str, str]]]:
    rows, _ = store.read_json(home / "cwd.ndjson")
    index: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        index.setdefault(row["session_id"], []).append((row["at"], row["cwd"]))
    for entries in index.values():
        entries.sort()
    return index


def project_at(index: dict, session_id: str, at: str, fallback: str) -> str:
    entries = index.get(session_id)
    if not entries:
        return fallback
    pos = bisect_right([e[0] for e in entries], at)
    if pos == 0:
        return fallback
    return Path(entries[pos - 1][1]).name or fallback
