from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
TASK_NAME = re.compile(r"^T-\d{4}$")


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmwiki")
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="vault 생성")
    init_p.add_argument("--force", action="store_true")

    sub.add_parser("ingest", help="claude-mem 증분 임포트")
    sub.add_parser("compile", help="이벤트에서 vault 뷰 재생성")
    sub.add_parser("lint")
    sub.add_parser("status")

    new_p = sub.add_parser("new", help="태스크 생성")
    new_p.add_argument("--project", required=True)
    new_p.add_argument("--title")
    new_p.add_argument("--bind")

    st_p = sub.add_parser("set-status")
    st_p.add_argument("--task", required=True)
    st_p.add_argument("--status", required=True,
                      choices=["queued", "doing", "blocked", "review", "done"])

    bind_p = sub.add_parser("bind")
    bind_p.add_argument("--session", required=True)
    bind_p.add_argument("--task", required=True)

    unbind_p = sub.add_parser("unbind")
    unbind_p.add_argument("--session", required=True)

    dis_p = sub.add_parser("dismiss")
    dis_p.add_argument("--session", action="append", default=[])
    dis_p.add_argument("--project")
    dis_p.add_argument("--before")

    ses_p = sub.add_parser("sessions")
    ses_p.add_argument("--unclassified", action="store_true")
    ses_p.add_argument("--project")
    ses_p.add_argument("--days", type=int)

    open_p = sub.add_parser("list-open")
    open_p.add_argument("--project")
    open_p.add_argument("--format", choices=["text", "brief"], default="text")

    search_p = sub.add_parser("search")
    search_p.add_argument("query")

    les_p = sub.add_parser("lessons", help="실패한 시도 후보. 기계는 후보까지만 만든다")
    les_sub = les_p.add_subparsers(dest="lessons_cmd")
    les_list = les_sub.add_parser("list")
    les_list.add_argument("--project")
    les_list.add_argument("--days", type=int, default=30)
    les_list.add_argument("--min-score", type=int, default=2)
    les_list.add_argument("--limit", type=int, default=20)
    les_list.add_argument("--all-projects", action="store_true",
                          help="노트가 없는 프로젝트도 포함한다")
    les_acc = les_sub.add_parser("accept")
    les_acc.add_argument("ref")
    les_acc.add_argument("--text", required=True)
    les_dis = les_sub.add_parser("dismiss")
    les_dis.add_argument("ref")
    les_dis.add_argument("--reason", default="")

    lib_p = sub.add_parser("library", help="가져온 자료")
    lib_sub = lib_p.add_subparsers(dest="library_cmd")
    lib_sub.add_parser("ingest")
    lib_sub.add_parser("pending")
    lib_done = lib_sub.add_parser("done")
    lib_done.add_argument("slug")
    lib_org = lib_sub.add_parser("set-origin")
    lib_org.add_argument("slug")
    lib_org.add_argument("origin")
    lib_rs = lib_sub.add_parser("resync", help="원본이 바뀐 노트를 재검토로 되돌린다")
    lib_rs.add_argument("slug")

    snap_p = sub.add_parser("snapshot")
    snap_p.add_argument("--keep", type=int, default=14)

    serve_p = sub.add_parser("serve", help="읽기 전용 웹 뷰")
    serve_p.add_argument("--port", type=int, default=8391)
    serve_p.add_argument("--refresh", type=int, default=60,
                         help="N초마다 ingest. 0이면 끔. vault 는 건드리지 않는다")
    serve_p.add_argument("--bind", default="127.0.0.1",
                         help="기본은 localhost. 외부 노출은 tailscale serve 에 맡긴다")

    sub.add_parser("migrate-host", help="event_id 에 호스트 네임스페이스 부여")
    sub.add_parser("hook-session-start")
    sub.add_parser("hook-user-prompt")
    return p


def _payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}


def _project_at(cfg, payload: dict) -> str | None:
    """Turn cwd into a project slug through the same normalization compile uses.

    Reimplementing the normalization here would diverge from the slug compile
    wrote into the frontmatter, and the filter would match nothing. The blocklist
    and mapping are owned by config (spec 5.4), so go through that path as is.
    """
    cwd = str(payload.get("cwd") or "")
    if not cwd:
        return None
    return _load("compiler").safe_slug(cfg.resolve_project(Path(cwd).name))


def _hook_session_start(home: Path, vault: Path, cfg) -> None:
    payload = _payload()
    session_id = str(payload.get("session_id") or "")
    name = str(payload.get("session_name") or "")
    tasks = _load("tasks")
    if session_id and TASK_NAME.match(name) and tasks.path_for(vault, name).exists():
        tasks.bind(home, session_id, name)
    queries = _load("queries")
    # Spec 8.3 says to inject the open tasks "of that project". Without the
    # filter, project B tasks leak into a project A session and fill the 5-item
    # cap, bringing back through the injection path the mixing 8.2 blocked.
    context = queries.brief(
        queries.list_open(vault, project=_project_at(cfg, payload)), max_chars=1000
    )
    print(json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
        ensure_ascii=False,
    ))


def _hook_user_prompt(home: Path, vault: Path) -> None:
    payload = _payload()
    session_id, cwd = str(payload.get("session_id") or ""), str(payload.get("cwd") or "")
    if session_id and cwd:
        _load("cwdmap").record(
            home, session_id, cwd, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _load("config")
    home = config.home()
    vault = config.vault(home)
    cfg = config.load(home)

    # Hooks must never block the session, no matter what happens.
    if args.command in ("hook-session-start", "hook-user-prompt"):
        try:
            if args.command == "hook-session-start":
                _hook_session_start(home, vault, cfg)
            else:
                _hook_user_prompt(home, vault)
        except BaseException:
            pass
        return 0

    if args.command == "serve":
        _load("webview").serve(home, vault, cfg, args.bind, args.port, args.refresh)
        return 0

    if args.command == "migrate-host":
        print(_load("migrate").namespace_events(home))
        return 0

    if args.command == "init":
        print(_load("scaffold").init(vault, home, args.force))
        return 0

    if args.command == "ingest":
        db = Path.home() / ".claude-mem" / "claude-mem.db"
        print(_load("ingest").run(home, db))
        return 0

    if args.command in ("lint", "compile"):
        # Running the first compile without config.toml creates junk pages named
        # after things like the home directory, and they land in the index. Spec
        # 5.4 warned about this, and it actually happened once.
        if not (home / "config.toml").exists():
            print(f"error: {home}/config.toml 이 없다. 먼저 'llmwiki init' 을 실행하라",
                  file=sys.stderr)
            return 1
        errors, warnings = _load("linter").run(home, vault, cfg)
        for w in warnings:
            print(f"warn: {w}")
        if errors:
            for e in errors:
                print(f"error: {e}", file=sys.stderr)
            if args.command == "compile":
                print("lint 에러로 compile 을 중단한다", file=sys.stderr)
            return 1
        if args.command == "lint":
            return 0
        result = _load("compiler").run(home, vault, cfg)
        # The vault-swap warning must not get buried in the result dict. It means
        # human-written text could disappear, so emit it separately on stderr.
        if result.get("vault_warning"):
            print(f"warn: {result['vault_warning']}", file=sys.stderr)
        print(result)
        return 0

    tasks, queries = _load("tasks"), _load("queries")

    if args.command == "new":
        print(tasks.create(home, vault, args.project, args.title, args.bind))
        return 0
    if args.command == "set-status":
        tasks.set_status(vault, args.task, args.status)
        return 0
    if args.command == "bind":
        previous = tasks.bind(home, args.session, args.task)
        if previous:
            print(f"warn: {args.session} 가 {previous} 에서 {args.task} 로 옮겨짐", file=sys.stderr)
        return 0
    if args.command == "unbind":
        tasks.unbind(home, args.session)
        return 0
    if args.command == "dismiss":
        targets = list(args.session)
        if args.project or args.before:
            for row in queries.unclassified(home, cfg, project=args.project):
                if args.before and row["at"][:10] >= args.before:
                    continue
                targets.append(row["session_id"])
        print(tasks.dismiss(home, sorted(set(targets))))
        return 0
    if args.command == "sessions":
        for row in queries.unclassified(home, cfg, args.project, args.days):
            nxt = (row.get("next_steps") or "").replace("\n", " ")[:80]
            print(f"{row['session_id'][:8]}  {row['project']:<24} {row['at'][:10]}  {nxt}")
        return 0
    if args.command == "list-open":
        rows = queries.list_open(vault, args.project)
        print(queries.brief(rows) if args.format == "brief"
              else "\n".join(f"{t['id']} [{t.get('status')}] {t.get('title')}" for t in rows))
        return 0
    if args.command == "status":
        result = queries.status(home, vault, cfg)
        for label, key in (("진행 중", "doing"), ("정체 경고", "stale"), ("대기 큐", "queued")):
            print(f"\n[{label}] {len(result[key])}건")
            for t in result[key]:
                print(f"  {t['id']}  {t.get('title')}  (마지막 {t.get('last_active') or '없음'})")
        return 0
    if args.command == "search":
        rg = shutil.which("rg")
        if not rg:
            print("rg 가 설치돼 있지 않다", file=sys.stderr)
            return 1
        return subprocess.call([rg, "--heading", "--line-number", args.query, str(vault)])
    if args.command == "lessons":
        lessons = _load("lessons")
        cmd = getattr(args, "lessons_cmd", None) or "list"
        if cmd == "list":
            rows = lessons.candidates(
                home, cfg, vault=vault, project=args.project, days=args.days,
                min_score=args.min_score, limit=args.limit,
            )
            dropped = [r for r in rows if not r["note_exists"]]
            if not args.all_projects:
                rows = [r for r in rows if r["note_exists"]]
            print(lessons.render(rows))
            if dropped and not args.all_projects:
                names = ", ".join(sorted({r["project"] for r in dropped}))
                print(f"\n(노트 없는 프로젝트 {len(dropped)}건 제외: {names}"
                      f" — --all-projects 로 볼 수 있다)")
            return 0
        try:
            cand = lessons.resolve(home, cfg, args.ref)
            if cmd == "accept":
                print(lessons.accept(home, vault, cand, args.text))
            else:
                lessons.dismiss(home, cand, args.reason)
                print(f'기각: {cand["ref"]} ({cand["project"]})')
        except (KeyError, ValueError, FileNotFoundError) as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    if args.command == "library":
        library = _load("library")
        cmd = getattr(args, "library_cmd", None) or "pending"
        if cmd == "ingest":
            print(library.ingest(vault))
            return 0
        if cmd == "pending":
            rows = library.pending(vault)
            print("\n".join(f'{r["slug"]}\t{r["source"]}\t{r["added"]}' for r in rows)
                  or "대기 중인 자료 없음")
            return 0
        try:
            if cmd == "set-origin":
                print(library.set_origin(vault, args.slug, args.origin))
            elif cmd == "resync":
                print(library.resync(vault, args.slug))
            else:
                print(library.mark_done(vault, args.slug))
        except (ValueError, FileNotFoundError) as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    if args.command == "snapshot":
        dest = home / "snapshots"
        print(_load("snapshot").run(vault, home, dest, keep=args.keep))
        return 0

    print(f"not implemented: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
