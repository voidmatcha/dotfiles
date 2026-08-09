from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
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


store, merge, vaultio = _load("store"), _load("merge"), _load("vaultio")

OPEN_STATUSES = ("doing", "queued", "blocked", "review")


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bindings(home: Path) -> dict[str, dict]:
    rows, _ = store.read_json(home / "bindings.ndjson")
    rows.sort(key=lambda r: r.get("at", ""))
    view: dict[str, dict] = {}
    for row in rows:
        view[row["session_id"]] = {
            "task_id": row.get("task_id"),
            "dismissed": bool(row.get("dismissed", False)),
        }
    return view


def _merged(home: Path, cfg=None) -> list[dict]:
    """compiler 와 같은 정제를 거친다. 차단/매핑을 안 거치면 대시보드에
    차단된 프로젝트가 다시 나타난다."""
    events, _ = store.read_json(home / "events.ndjson")
    if cfg is None:
        return merge.by_session_project(events)
    compiler = _load("compiler")
    resolved = []
    for event in events:
        slug = cfg.resolve_project(event["project"])
        resolved.append({**event, "project": compiler.safe_slug(slug)})
    return merge.by_session_project(resolved)


def unclassified(home: Path, cfg, project: str | None = None,
                 days: int | None = None) -> list[dict]:
    window = _cutoff(days if days is not None else cfg.unclassified_days)
    binds = _bindings(home)
    out = []
    for row in _merged(home, cfg):
        binding = binds.get(row["session_id"]) or {}
        if binding.get("task_id") or binding.get("dismissed"):
            continue
        if not (row.get("next_steps") or "").strip():
            continue
        if row["merged_from"] < 2 and not row.get("files_edited"):
            continue
        if row["at"] < window:
            continue
        if project and row["project"] != project:
            continue
        out.append(row)
    return sorted(out, key=lambda r: r["at"], reverse=True)


def activity(home: Path, cfg) -> list[dict]:
    window = _cutoff(cfg.unclassified_days)
    pending = {r["session_id"] for r in unclassified(home, cfg)}
    buckets: dict[str, dict] = {}
    for row in _merged(home, cfg):
        if row["at"] < window:
            continue
        entry = buckets.setdefault(
            row["project"],
            {"project": row["project"], "sessions": 0, "unclassified": 0, "last": ""},
        )
        entry["sessions"] += 1
        entry["unclassified"] += 1 if row["session_id"] in pending else 0
        entry["last"] = max(entry["last"], row["at"])
    return sorted(buckets.values(), key=lambda e: e["sessions"], reverse=True)


def _tasks(vault: Path) -> list[dict]:
    folder = vault / "tasks"
    out = []
    for page in sorted(folder.glob("T-*.md")) if folder.exists() else []:
        meta, _ = vaultio.read_page(page)
        if meta:
            out.append(meta)
    return out


def list_open(vault: Path, project: str | None = None, limit: int = 5) -> list[dict]:
    rows = [t for t in _tasks(vault) if t.get("status") in OPEN_STATUSES]
    if project:
        rows = [t for t in rows if t.get("project") == project]
    rows.sort(key=lambda t: (t.get("status") != "doing", str(t.get("last_active", ""))))
    return rows[:limit]


def brief(rows: list[dict], max_chars: int = 1000) -> str:
    lines, total = [], 0
    for task in rows:
        line = f"- {task['id']} [{task.get('status', '?')}] {str(task.get('title', ''))[:60]}"
        if total + len(line) + 1 > max_chars:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def live_activity(home: Path) -> dict[str, dict]:
    """태스크별 최신 활동을 이벤트에서 직접 계산한다.

    프론트매터의 last_active 는 compile 이 써주는데 compile 은 야간에만 돈다.
    ingest 는 vault 를 건드리지 않아 자주 돌려도 안전하므로, 이벤트만으로
    계산하면 compile 없이도 상태가 신선해진다.
    """
    binds = _bindings(home)
    out: dict[str, dict] = {}
    for row in _merged(home):
        task_id = (binds.get(row["session_id"]) or {}).get("task_id")
        if not task_id:
            continue
        entry = out.setdefault(task_id, {"last_active": "", "last_harness": "", "session_count": 0})
        entry["session_count"] += 1
        if row["at"] > entry["last_active"]:
            entry["last_active"] = row["at"]
            entry["last_harness"] = row.get("harness", "")
    return out


def status(home: Path, vault: Path, cfg, live: bool = True) -> dict:
    stale_before = _cutoff(cfg.stale_days)[:10]
    overlay = live_activity(home) if live else {}
    doing, stale, queued = [], [], []
    for task in _tasks(vault):
        extra = overlay.get(str(task.get("id", "")))
        if extra and extra["last_active"]:
            task = {**task, "last_active": extra["last_active"][:10],
                    "last_harness": extra["last_harness"],
                    "session_count": extra["session_count"]}
        if task.get("status") == "queued":
            queued.append(task)
        elif task.get("status") == "doing":
            # 활동 기록이 없으면 생성일로 판단한다. 그러지 않으면 방금 만든
            # 태스크가 곧바로 정체 경고로 떨어진다.
            seen = str(task.get("last_active") or task.get("created") or "")
            (stale if seen < stale_before else doing).append(task)
    return {"doing": doing, "stale": stale, "queued": queued}
