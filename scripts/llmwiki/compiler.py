from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime, timezone
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


store, merge, render = _load("store"), _load("merge"), _load("render")
config = _load("config")
markers, vaultio = _load("markers"), _load("vaultio")

OPEN_STATUSES = ("doing", "queued", "blocked", "review")
_UNSAFE_SLUG = re.compile(r"[^\w가-힣.-]+")
SKELETON = "## 지금 상태\n\n## 실패한 시도 (다시 하지 말 것)\n\n## 결정과 근거\n"


def safe_slug(raw: str) -> str:
    """파일명으로 쓸 수 있게 만든다.

    claude-mem 의 project 에는 'ui-skills/2026-06-27-adcker4' 같은 워크트리
    경로가 들어온다. 그대로 쓰면 하위 디렉터리가 생겨 페이지가 흩어지고
    index 링크가 깨진다. 실제 데이터에서 28개 중 5개가 이 형태였다.
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
    """updated 를 빼고 비교한 뒤, 실제로 바뀐 경우에만 updated 를 갱신한다.

    updated 를 무조건 새로 쓰면 compile 을 두 번 돌릴 때마다 모든 페이지가
    달라져 멱등성이 깨진다. 스펙 검증 1번이 이것을 잡는다.
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
    """이 볼트가 전에도 여기였는지 확인하고, 아니면 경고를 돌려준다.

    볼트는 순수한 파생물이 아니다. GEN 마커 안쪽은 events 에서 다시 만들
    수 있지만 마커 밖의 글 - 지금 상태, 실패한 시도, 결정과 근거 - 과
    tasks/ 아래 태스크 페이지는 볼트에만 존재한다. 경로를 바꾸고 compile
    하면 새 위치에 볼트가 생기고 그것들이 조용히 사라진다. 실측했다.

    스탬프는 한 번만 쓴다. 매번 갱신하면 compile 이 늘 변경을 만들어
    멱등성이 깨진다.
    """
    here = str(vault.resolve())
    warning = None

    # home 쪽 기록. 교체를 가로질러 변하지 않는 것은 home 뿐이라, 설정을 빈
    # 새 경로로 돌린 경우는 여기서만 잡힌다. 볼트 쪽 표식은 볼트와 함께
    # 움직이므로 그 경우 새 위치에 찍히고 조용히 넘어간다.
    state_path = home / "state.json"
    previous = ""
    if state_path.exists():
        try:
            previous = str(store.load_state(state_path).get("vault", "") or "")
        except Exception:  # state 를 못 읽어도 compile 을 막지 않는다
            previous = ""
    if previous and previous != here:
        warning = (f"마지막으로 컴파일한 볼트는 {previous} 였고 지금은 {here} 다. "
                   f"GEN 영역은 다시 만들어지지만 직접 쓴 글과 tasks/ 는 볼트에만 "
                   f"있다. 옛 볼트를 확인하라")

    # 볼트 쪽 표식. 볼트를 통째로 옮기거나 복사한 경우를 잡는다.
    stamp = vault / STAMP
    if not stamp.exists():
        vault.mkdir(parents=True, exist_ok=True)
        vaultio.write_atomic(stamp, here + "\n")
    else:
        was = stamp.read_text(encoding="utf-8").strip()
        if was != here and warning is None:
            warning = (f"이 볼트는 {was} 에서 만들어졌고 지금은 {here} 다. "
                       f"옮긴 것이 맞으면 {stamp} 를 지워라")

    # state 갱신은 호출자가 컴파일을 끝낸 뒤에 한다. 여기서 적으면 뒤에서
    # 죽은 실행이 경고를 삼킨다 - state 는 이미 새 볼트라고 적혔는데 경고는
    # 출력되지 못했고, 재시도는 조용히 지나간다. 재지정이 실패하는 경우는
    # 마운트 안 된 볼륨이나 권한 문제라 드물지도 않다.
    return warning, (previous != here), previous


def run(home: Path, vault: Path, cfg) -> dict:
    vault_warning, _record_vault, _previous_vault = _check_vault_identity(home, vault)
    events, _ = store.read_json(home / "events.ndjson")
    resolved = []
    for event in events:
        raw = event["project"]
        slug = cfg.resolve_project(raw)
        # 어디서 왔는지를 잃으면 되돌릴 수 없다. mapping 으로 꺼내려면
        # 원래 이름이 페이지에 보여야 한다.
        origin = raw if slug == config.UNFILED and raw != config.UNFILED else None
        resolved.append({**event, "project": safe_slug(slug), "origin": origin})

    rows = merge.by_session_project(resolved)
    binds = bindings_view(home)

    per_project: dict[str, list[dict]] = {}
    for row in rows:
        per_project.setdefault(row["project"], []).append(row)

    # 프로젝트별 열린 태스크 수. 태스크 페이지의 project 프론트매터 기준으로 센다
    # (스펙 4.3: 크로스 프로젝트 바인딩이 있어도 태스크의 project 가 기준이다).
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

    # 태스크 진행 로그. 바인딩된 세션만 담는다.
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
    # 스펙 5.5: 상태 변화만 기록한다. 매 실행마다 붙이면 log.md 가 무한 증식하고
    # compile 의 멱등성도 깨진다.
    if changed:
        vaultio.append_log(vault, "compile", f"projects={len(per_project)} tasks={task_count}")

    # 컴파일이 끝난 뒤에야 이 볼트를 "마지막으로 쓴 곳" 으로 기록한다.
    #
    # 교체가 없어도 매번 확인한다. 교체할 때만 손보면 옛 볼트를 지운 뒤에도
    # 그 경로가 state 에 남고, 나중에 같은 자리에 무언가 생기면 이미 끝난
    # 교체의 경고가 되살아난다. 기본 경로는 특히 재사용될 만하다.
    here = str(vault.resolve())
    previous = _previous_vault if _record_vault else ""
    state_path = home / "state.json"
    current = store.load_state(state_path) if state_path.exists() else {}

    # 목록으로 쌓는다. 단일 슬롯이면 A→B→C 로 두 번 옮길 때 A 가 묻히고,
    # A 에 남은 글은 아무도 알리지 않는다. 사라진 경로는 여기서 빠지므로
    # 목록이 무한히 자라지도 않는다.
    stranded = [v for v in current.get("vaults_previous", [])
                if v != here and Path(v).is_dir()]
    if previous and previous != here and previous not in stranded \
            and Path(previous).is_dir():
        stranded.append(previous)

    # 바뀔 것이 없으면 쓰지 않는다. 매 실행마다 쓰면 잠금과 파일 교체가
    # 공짜가 아니고, 멱등성 확인도 흐려진다.
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
