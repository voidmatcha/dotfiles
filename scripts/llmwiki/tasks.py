from __future__ import annotations

import importlib.util
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent


def _load(name: str):
    """Reuse an already-loaded module.

    Without the cache, mutual imports turn into infinite recursion. It actually
    hung on the structure where compiler calls queries and queries calls compiler.
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


store, vaultio = _load("store"), _load("vaultio")

BODY = """## 목표

## 완료 조건

<!-- GEN:progress -->
_아직 기록 없음_
<!-- /GEN:progress -->

## 실패한 시도 (다시 하지 말 것)

## 산출물
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    cleaned = re.sub(r"[^\w가-힣]+", "-", normalized, flags=re.UNICODE)
    return cleaned.strip("-").lower()[:40] or "task"


def path_for(vault: Path, task_id: str) -> Path:
    folder = vault / "tasks"
    matches = sorted(folder.glob(f"{task_id}*.md")) if folder.exists() else []
    return matches[0] if matches else folder / f"{task_id}.md"


def create(home: Path, vault: Path, project: str, title: str | None = None,
           bind_session: str | None = None, next_steps_hint: str = "") -> str:
    if not title:
        first = re.split(r"[.。\n]", next_steps_hint.strip())[0].strip()
        title = first or "제목 없음"
    task_id = store.next_task_id(home / "state.json")
    meta = {
        "type": "task", "id": task_id, "title": title, "project": project,
        "status": "doing" if bind_session else "queued", "priority": 2, "blocked_by": "",
        "last_active": "", "last_harness": "", "session_count": 0,
        "created": date.today().isoformat(), "updated": date.today().isoformat(),
    }
    vaultio.write_page(vault / "tasks" / f"{task_id}-{slugify(title)}.md", meta, BODY)
    if bind_session:
        bind(home, bind_session, task_id)
    return task_id


def _current(home: Path, session_id: str) -> str | None:
    rows, _ = store.read_json(home / "bindings.ndjson")
    rows.sort(key=lambda r: r.get("at", ""))
    latest = None
    for row in rows:
        if row.get("session_id") == session_id:
            latest = row
    return latest.get("task_id") if latest else None


def bind(home: Path, session_id: str, task_id: str) -> str | None:
    """Return the previous binding's ID if there was one. The caller warns."""
    previous = _current(home, session_id)
    store.append_json(home / "bindings.ndjson", {
        "session_id": session_id, "task_id": task_id, "dismissed": False, "at": _now(),
    })
    return previous if previous and previous != task_id else None


def unbind(home: Path, session_id: str) -> None:
    store.append_json(home / "bindings.ndjson", {
        "session_id": session_id, "task_id": None, "dismissed": False, "at": _now(),
    })


def dismiss(home: Path, session_ids: list[str]) -> int:
    for session_id in session_ids:
        store.append_json(home / "bindings.ndjson", {
            "session_id": session_id, "task_id": None, "dismissed": True, "at": _now(),
        })
    return len(session_ids)


def set_status(vault: Path, task_id: str, status: str) -> None:
    page = path_for(vault, task_id)
    meta, body = vaultio.read_page(page)
    meta["status"] = status
    meta["updated"] = date.today().isoformat()
    vaultio.write_page(page, meta, body)
