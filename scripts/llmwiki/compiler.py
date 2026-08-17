from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime, timezone
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


store, merge, render = _load("store"), _load("merge"), _load("render")
config = _load("config")
markers, vaultio = _load("markers"), _load("vaultio")

OPEN_STATUSES = ("doing", "queued", "blocked", "review")
_UNSAFE_SLUG = re.compile(r"[^\w가-힣.-]+")
SKELETON = "## 지금 상태\n\n## 실패한 시도 (다시 하지 말 것)\n\n## 결정과 근거\n"


def safe_slug(raw: str) -> str:
    """Make a value usable as a filename.

    claude-mem's project field carries worktree paths such as
    'ui-skills/2026-06-27-adcker4'. Used as is, it creates subdirectories, so
    pages scatter and index links break. In the real data 5 of 28 had this shape.
    """
    return _UNSAFE_SLUG.sub("-", raw).strip("-") or "unnamed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_since(stamp: str) -> int:
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return (_now() - when).days


def bindings_view(home: Path) -> dict[str, dict]:
    rows, _ = store.read_json(home / "bindings.ndjson")
    rows.sort(key=lambda r: r.get("at", ""))
    view: dict[str, dict] = {}
    for row in rows:
        view[row["session_id"]] = {
            "task_id": row.get("task_id"),
            "dismissed": bool(row.get("dismissed", False)),
        }
    return view


def write_if_changed(page: Path, meta: dict, body: str, stamp: str) -> bool:
    """Compare with updated excluded, and bump updated only if something changed.

    Always rewriting updated makes every page differ on a second compile run,
    which breaks idempotence. Spec verification item 1 catches this.
    """
    previous, _ = vaultio.read_page(page)
    candidate = {k: v for k, v in meta.items() if k != "updated"}
    settled = {k: v for k, v in previous.items() if k != "updated"}
    _, previous_body = vaultio.read_page(page)
    if page.exists() and candidate == settled and previous_body == body:
        return False
    meta["updated"] = stamp
    vaultio.write_page(page, meta, body)
    return True


def _task_pages(vault: Path) -> list[Path]:
    folder = vault / "tasks"
    return sorted(folder.glob("T-*.md")) if folder.exists() else []


STAMP = ".llmwiki-vault"


def _check_vault_identity(home: Path, vault: Path) -> tuple[str | None, bool, str]:
    """Check whether this vault was here before, and return a warning if not.

    The vault is not a pure derivative. What is inside the GEN markers can be
    rebuilt from events, but the prose outside the markers - 지금 상태, 실패한
    시도, 결정과 근거 - and the task pages under tasks/ exist only in the vault.
    Change the path and compile, and a vault appears at the new location while
    those quietly disappear. Measured for real.

    The stamp is written once. Refreshing it every time would make compile always
    produce a change and break idempotence.
    """
    here = str(vault.resolve())
    warning = None

    # The home-side record. Only home stays fixed across a swap, so pointing the
    # config at an empty new path is caught here alone. The vault-side stamp
    # travels with the vault, so it just gets written at the new spot in silence.
    state_path = home / "state.json"
    previous = ""
    if state_path.exists():
        try:
            previous = str(store.load_state(state_path).get("vault", "") or "")
        except Exception:  # an unreadable state must not block compile
            previous = ""
    if previous and previous != here:
        warning = (f"마지막으로 컴파일한 볼트는 {previous} 였고 지금은 {here} 다. "
                   f"GEN 영역은 다시 만들어지지만 직접 쓴 글과 tasks/ 는 볼트에만 "
                   f"있다. 옛 볼트를 확인하라")

    # The vault-side stamp. Catches a vault moved or copied wholesale.
    stamp = vault / STAMP
    if not stamp.exists():
        vault.mkdir(parents=True, exist_ok=True)
        vaultio.write_atomic(stamp, here + "\n")
    else:
        was = stamp.read_text(encoding="utf-8").strip()
        if was != here and warning is None:
            warning = (f"이 볼트는 {was} 에서 만들어졌고 지금은 {here} 다. "
                       f"옮긴 것이 맞으면 {stamp} 를 지워라")

    # The caller updates state after the compile finishes. Writing it here lets a
    # run that dies later swallow the warning - state already says the new vault
    # while the warning never got printed, and the retry passes silently.
    # Repointing fails on unmounted volumes or permissions, which is not rare.
    return warning, (previous != here), previous


def run(home: Path, vault: Path, cfg) -> dict:
    vault_warning, _record_vault, _previous_vault = _check_vault_identity(home, vault)
    events, _ = store.read_json(home / "events.ndjson")
    resolved = []
    for event in events:
        raw = event["project"]
        slug = cfg.resolve_project(raw)
        # Losing where it came from makes it unrecoverable. To pull it out with
        # a mapping, the original name has to be visible on the page.
        origin = raw if slug == config.UNFILED and raw != config.UNFILED else None
        resolved.append({**event, "project": safe_slug(slug), "origin": origin})

    rows = merge.by_session_project(resolved)
    binds = bindings_view(home)

    per_project: dict[str, list[dict]] = {}
    for row in rows:
        per_project.setdefault(row["project"], []).append(row)

    # Open task count per project. Counted by the task page's project frontmatter
    # (spec 4.3: even with a cross-project binding, the task's project rules).
    open_by_project: dict[str, int] = {}
    task_meta: dict[str, dict] = {}
    for page in _task_pages(vault):
        meta, _body = vaultio.read_page(page)
        if not meta.get("id"):
            continue
        task_meta[str(meta["id"])] = meta
        if meta.get("status") in OPEN_STATUSES:
            key = str(meta.get("project", ""))
            open_by_project[key] = open_by_project.get(key, 0) + 1

    promoted: list[str] = []
    archived: list[str] = []
    changed = False
    index_entries: list[tuple[str, str]] = []

    for slug, project_rows in sorted(per_project.items()):
        sessions = len({r["session_id"] for r in project_rows})
        page = vault / "projects" / f"{slug}.md"
        if sessions < cfg.active_threshold and not page.exists():
            continue
        if sessions >= cfg.active_threshold and not page.exists():
            promoted.append(slug)

        meta, body = vaultio.read_page(page)
        if not body.strip():
            body = SKELETON

        stamps = sorted(r["at"] for r in project_rows)
        merged_meta = {
            "type": "project",
            "slug": slug,
            "status": meta.get("status", "active"),
            **{k: v for k, v in meta.items() if k not in ("type", "slug", "status")},
            "sessions": sessions,
            "harnesses": sorted({r.get("harness", "?") for r in project_rows}),
            "first_seen": stamps[0][:10],
            "last_active": stamps[-1][:10],
            "open_tasks": open_by_project.get(slug, 0),
            "updated": meta.get("updated", ""),
        }

        if merged_meta["status"] == "active" and _days_since(stamps[-1]) > cfg.archive_days:
            merged_meta["status"] = "archived"
            archived.append(slug)

        recent = sorted(project_rows, key=lambda r: r["at"], reverse=True)[:10]
        timeline = "\n".join(
            render.timeline_line(r, (binds.get(r["session_id"]) or {}).get("task_id"))
            for r in recent
        )
        open_links = "\n".join(
            f"- [[{tid}]] {task_meta[tid].get('title', '')}"
            for tid in sorted(task_meta)
            if task_meta[tid].get("status") in OPEN_STATUSES
            and str(task_meta[tid].get("project", "")) == slug
        )
        body = markers.replace(body, "open-tasks", open_links or "_없음_")
        body = markers.replace(body, "timeline", timeline or "_없음_")
        changed |= write_if_changed(page, merged_meta, body, _now().strftime("%Y-%m-%dT%H:%M:%SZ"))

        if merged_meta["status"] == "active":
            index_entries.append(
                (stamps[-1], f"- projects/{slug}.md — project — {sessions}세션")
            )

    # Task progress log. Only bound sessions go in.
    by_task: dict[str, list[dict]] = {}
    for row in rows:
        task_id = (binds.get(row["session_id"]) or {}).get("task_id")
        if task_id:
            by_task.setdefault(task_id, []).append(row)

    task_count = 0
    tasks = _load("tasks")
    for task_id in sorted(task_meta):
        page = tasks.path_for(vault, task_id)
        meta, body = vaultio.read_page(page)
        if not meta:
            continue
        task_count += 1
        task_rows = sorted(by_task.get(task_id, []), key=lambda r: r["at"])
        owned = {
            "last_active": task_rows[-1]["at"][:10] if task_rows else "",
            "last_harness": task_rows[-1].get("harness", "") if task_rows else "",
            "session_count": len(task_rows),
        }
        progress = "\n\n".join(
            render.progress_line(r, cfg.truncate_request, cfg.truncate_next) for r in task_rows
        ) or "_아직 기록 없음_"
        body = markers.replace(body, "progress", progress)
        changed |= write_if_changed(page, {**meta, **owned}, body, _now().strftime("%Y-%m-%d"))
        if meta.get("status") in OPEN_STATUSES:
            index_entries.append((str(owned["last_active"]), f"- tasks/{page.name} — task — {meta.get('title', '')}"))

    index_entries.sort(key=lambda e: e[0], reverse=True)
    lines, total = [], 0
    truncated = False
    for _, line in index_entries:
        if total + len(line) + 1 > cfg.index_max_chars:
            truncated = True
            break
        lines.append(line)
        total += len(line) + 1
    vaultio.write_atomic(vault / "index.md", "# index\n\n" + "\n".join(lines) + "\n")

    _write_dashboard(home, vault, cfg)

    for slug in promoted:
        vaultio.append_log(vault, "promote", f"{slug} 활성 승격")
    for slug in archived:
        vaultio.append_log(vault, "archive", f"{slug} 강등 ({cfg.archive_days}일 무활동)")
    # Spec 5.5: record only state changes. Appending on every run makes log.md
    # grow without bound and breaks compile's idempotence too.
    if changed:
        vaultio.append_log(vault, "compile", f"projects={len(per_project)} tasks={task_count}")

    # Only after the compile finishes is this vault recorded as "last written to".
    #
    # Checked every time, even with no swap. Touching it only on a swap leaves the
    # old vault's path in state after it is deleted, and if something later
    # appears at the same spot the warning for an already-finished swap comes back
    # to life. The default path is especially likely to get reused.
    here = str(vault.resolve())
    previous = _previous_vault if _record_vault else ""
    state_path = home / "state.json"
    current = store.load_state(state_path) if state_path.exists() else {}

    # Accumulated as a list. With a single slot, moving twice A to B to C buries A
    # and nobody reports the prose left behind in A. Vanished paths drop out here,
    # so the list does not grow without bound either.
    stranded = [v for v in current.get("vaults_previous", [])
                if v != here and Path(v).is_dir()]
    if previous and previous != here and previous not in stranded \
            and Path(previous).is_dir():
        stranded.append(previous)

    # Do not write when nothing would change. Writing on every run is not free -
    # locking and file replacement cost something, and it muddies the idempotence
    # check.
    if current.get("vault") != here or current.get("vaults_previous", []) != stranded:
        store.update_state(state_path,
                           lambda st: st.update({"vault": here,
                                                 "vaults_previous": stranded}))

    return {
        "projects": len([e for e in index_entries if "— project —" in e[1]]),
        "tasks": task_count,
        "promoted": promoted,
        "archived": archived,
        "index_truncated": truncated,
        "vault_warning": vault_warning,
    }


def _write_dashboard(home: Path, vault: Path, cfg) -> None:
    dashboard = vault / "dashboard.md"
    if not dashboard.exists():
        return
    queries = _load("queries")
    header = "| 프로젝트 | 세션 | 미분류 | 마지막 |\n|---|---|---|---|"
    body_rows = "\n".join(
        f"| {a['project']} | {a['sessions']} | {a['unclassified']} | {a['last'][5:10]} |"
        for a in queries.activity(home, cfg)
    )
    section = f"## 프로젝트 활동 (최근 {cfg.unclassified_days}일)\n\n{header}\n{body_rows}"
    text = dashboard.read_text(encoding="utf-8")
    vaultio.write_atomic(dashboard, markers.replace(text, "activity", section))
