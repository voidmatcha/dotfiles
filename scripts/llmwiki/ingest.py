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


store = _load("store")
cwdmap = _load("cwdmap")
config = _load("config")

SOURCE = "claude-mem"


def snapshot_db(src: Path, dst: Path) -> None:
    """Make a consistent copy without touching the live WAL.

    The original is opened only with mode=ro. The copy is put back to
    journal_mode delete. The backup API copies the original's WAL mode as is, and
    opening a WAL database with mode=ro cannot create -shm/-wal, so it dies with
    'unable to open database file'. Confirmed on the real 268MB DB.
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
        # A WAL database with no -shm cannot be opened with mode=ro. It gets into
        # that state when there is no active connection at all. Opening the
        # original read-write is forbidden, because closing runs a checkpoint that
        # touches the real file. Copy the files as they are and recover from the
        # copy instead.
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
    # This is a copy, so no read-only enforcement is needed. snapshot_db is what
    # guarantees read-only access to the original.
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

    # Serialize the whole import against other ingests and against the migrate
    # rewrite. `seen` is a snapshot of events.ndjson taken before the slow SQLite
    # copy, so two overlapping runs (the 60s web refresher and the 04:00 nightly
    # job) select the same `s.id > watermark` rows and both append them; the
    # duplicate surfaces later as merged_from doubling. A run that loses the race
    # skips instead of waiting: ingest is incremental, so the next tick picks the
    # rows up, and waiting would stack refresher threads behind a slow snapshot.
    with store.lock_file(events_path, blocking=False) as acquired:
        if not acquired:
            held = store.load_state(state_path)
            return {"imported": 0, "watermark": int(held["watermark"].get(key, 0)),
                    "skipped": 0, "host": host, "locked": True}

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
        # Write the events first, raise the watermark after. If it dies in between,
        # event_id deduplication absorbs the rerun. In the opposite order, events are
        # silently lost.
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
        return {"imported": imported, "watermark": highest, "skipped": skipped,
                "host": host, "locked": False}
