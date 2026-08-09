from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import sys
import tempfile
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
cwdmap = _load("cwdmap")
config = _load("config")

SOURCE = "claude-mem"


def snapshot_db(src: Path, dst: Path) -> None:
    """라이브 WAL을 건드리지 않고 일관된 사본을 만든다.

    원본은 반드시 mode=ro 로만 연다. 사본은 journal_mode 를 delete 로 되돌린다.
    backup API 가 원본의 WAL 모드를 그대로 복사하는데, WAL 데이터베이스를
    mode=ro 로 열면 -shm/-wal 을 만들 수 없어 'unable to open database file' 로
    죽는다. 실제 268MB DB 에서 확인했다.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        _copy_files(src, dst)
        return
    try:
        con.execute("PRAGMA busy_timeout = 5000")
        out = sqlite3.connect(dst)
        try:
            with out:
                con.backup(out)
            out.execute("PRAGMA journal_mode = delete")
        finally:
            out.close()
    except sqlite3.OperationalError:
        # WAL 데이터베이스인데 -shm 이 없으면 mode=ro 로는 열 수 없다. 활성
        # 연결이 하나도 없을 때 이 상태가 된다. 원본을 읽기-쓰기로 여는 것은
        # 닫을 때 체크포인트가 돌아 본 파일을 건드리므로 금지다. 대신 파일을
        # 그대로 복사하고 사본에서 복구시킨다.
        _copy_files(src, dst)
    finally:
        con.close()


def _copy_files(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        side = Path(str(src) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(dst) + suffix))
    con = sqlite3.connect(dst)
    try:
        con.execute("PRAGMA journal_mode = delete")
    finally:
        con.close()


def rows_since(db: Path, watermark: int) -> list[dict]:
    # 사본이므로 읽기 전용 강제가 필요 없다. 읽기 전용 보장은 snapshot_db 가 한다.
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(
            """
            SELECT s.id, s.memory_session_id, s.project, s.request, s.investigated,
                   s.learned, s.completed, s.next_steps, s.files_read, s.files_edited,
                   s.notes, s.created_at,
                   COALESCE(k.platform_source, 'claude') AS harness
            FROM session_summaries s
            LEFT JOIN sdk_sessions k ON k.memory_session_id = s.memory_session_id
            WHERE s.id > ?
            ORDER BY s.id
            """,
            (watermark,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def _list(raw) -> list[str]:
    if not raw or raw in ("None", "[]"):
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


def watermark_key(host: str) -> str:
    return f"{SOURCE}:{host}"


def to_event(row: dict, host: str) -> dict:
    return {
        "event_id": f"{SOURCE}:{host}:{row['id']}",
        "host": host,
        "session_id": row["memory_session_id"],
        "harness": row["harness"],
        "project": row["project"],
        "at": row["created_at"],
        "request": row.get("request") or "",
        "investigated": row.get("investigated") or "",
        "learned": row.get("learned") or "",
        "completed": row.get("completed") or "",
        "next_steps": row.get("next_steps") or "",
        "notes": row.get("notes") or "",
        "files_read": _list(row.get("files_read")),
        "files_edited": _list(row.get("files_edited")),
    }


def run(home: Path, db: Path, host: str | None = None) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    host = host or config.host()
    key = watermark_key(host)
    events_path, state_path = home / "events.ndjson", home / "state.json"
    state = store.load_state(state_path)
    watermark = int(state["watermark"].get(key, 0))

    existing, _ = store.read_json(events_path)
    seen = {e["event_id"] for e in existing}

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "claude-mem.db"
        snapshot_db(db, copy)
        rows = rows_since(copy, watermark)

    imported = skipped = 0
    highest = watermark
    cwd_index = cwdmap.build(home)
    # 이벤트를 먼저 쓰고 워터마크를 나중에 올린다. 중간에 죽어도 event_id 중복
    # 제거가 재실행을 흡수한다. 반대 순서면 이벤트가 조용히 유실된다.
    for row in rows:
        event = to_event(row, host)
        event["project"] = cwdmap.project_at(
            cwd_index, event["session_id"], event["at"], event["project"]
        )
        highest = max(highest, int(row["id"]))
        if event["event_id"] in seen:
            skipped += 1
            continue
        store.append_json(events_path, event)
        seen.add(event["event_id"])
        imported += 1

    if highest > watermark:
        store.update_state(state_path, lambda s: s["watermark"].update({key: highest}))
    return {"imported": imported, "watermark": highest, "skipped": skipped, "host": host}
