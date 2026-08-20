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
config = _load("config")

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
    resolved = [{**e, "project": cfg.project_id(e["project"])} for e in events]
    return merge.by_session_project(resolved)


def unclassified(home: Path, cfg, project: str | None = None,
                 days: int | None = None) -> list[dict]:
    window = _cutoff(days if days is not None else cfg.unclassified_days)
    binds = _bindings(home)
    # Same identity rule as everywhere else: rows are canonical, so a hand-typed
    # --project has to go through the mapping and blocklist before it can be
    # compared, or 'Documents' matches nothing.
    wanted = _canonical(cfg, project) if project else None
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
        if wanted is not None and row["project"] != wanted:
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


def _canonical(cfg, raw: str) -> str:
    """Project identity for the read side.

    Without a cfg the mapping and blocklist are unknown, so apply only the slug
    - the half of the identity that carries no configuration. Callers that have
    a cfg should pass it, or a blocklisted name never lines up with 'unfiled'.
    """
    if not raw:
        return ""
    return cfg.project_id(raw) if cfg is not None else config.safe_slug(raw)


def _recency(task: dict) -> str:
    """Sort key for "most recently worked on".

    Falls back to created because last_active is written by compile, which runs
    overnight - a task made today still has an empty one. Sorting descending on
    an empty string would push a brand new task past the cap, which is the same
    silent disappearance this ordering exists to prevent. status() already falls
    back to created for the same reason.
    """
    return str(task.get("last_active") or task.get("created") or "")


def list_open(vault: Path, project: str | None = None, limit: int = 5,
              cfg=None) -> list[dict]:
    rows = [t for t in _tasks(vault) if t.get("status") in OPEN_STATUSES]
    if project:
        # Normalize both sides. Writers canonicalize from now on, but task pages
        # already in the vault hold raw --project strings, and an == against the
        # hook's slugged cwd matched nothing - the project silently got zero
        # injection and no error said why.
        want = _canonical(cfg, project)
        rows = [t for t in rows if _canonical(cfg, str(t.get("project", ""))) == want]
    # Most recent first, then hoist doing. Two stable passes, because a string
    # key cannot be negated to mix directions inside one sort. This used to sort
    # ascending, so the cap handed the hook the 5 stalest tasks and dropped the
    # one worked on yesterday; every other view is most-recent-first.
    rows.sort(key=_recency, reverse=True)
    rows.sort(key=lambda t: t.get("status") != "doing")
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
