from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
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
    """Go through the same normalization as compiler. Skipping the blocklist and
    mapping makes blocked projects reappear on the dashboard."""
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
    """Compute the latest activity per task straight from the events.

    The frontmatter's last_active is written by compile, and compile only runs at
    night. ingest does not touch the vault, so it is safe to run often; computing
    from the events alone keeps status fresh without a compile.
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
            # With no activity record, judge by the creation date. Otherwise a
            # freshly created task drops straight into the stale warning.
            seen = str(task.get("last_active") or task.get("created") or "")
            (stale if seen < stale_before else doing).append(task)
    return {"doing": doing, "stale": stale, "queued": queued}
