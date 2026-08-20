from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Callable

_DEFAULT_STATE = {"watermark": {}, "task_counter": 0, "version": 1}


@contextlib.contextmanager
def lock_file(path: Path, blocking: bool = True) -> Iterator[bool]:
    """Hold an exclusive advisory lock on `<path>.lock` for the block.

    This is the single locking primitive for the store. Anything that does a
    read-modify-write over a file another process may be appending to has to
    take it; a plain append via append_json does not.

    Yields True when the lock was taken. With blocking=False it yields False
    instead of raising when somebody else holds it, so a scheduled caller can
    skip a run rather than die. The lock is per open file description, so two
    threads in one process contend with each other exactly like two processes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as lock:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(lock.fileno(), flags)
        except OSError:
            # Only LOCK_NB gets here: somebody else is mid-write.
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def append_json(path: Path, obj: dict) -> None:
    """Append one line with a single O_APPEND write; concurrent appends never clash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_json_raw(path: Path) -> list[tuple[dict | None, str]]:
    """Every non-blank line as (parsed, raw); an unparsable line parses to None.

    Readers that only consume data want read_json. Anything that rewrites the
    file needs this, so a half-written line can be carried over verbatim instead
    of being dropped on the floor.
    """
    if not path.exists():
        return []
    out: list[tuple[dict | None, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append((json.loads(line), line))
            except json.JSONDecodeError:
                out.append((None, line))
    return out


def read_json(path: Path) -> tuple[list[dict], int]:
    """Skip broken lines, counting them. A last line left half-written is common."""
    rows: list[dict] = []
    broken = 0
    for parsed, _raw in read_json_raw(path):
        if parsed is None:
            broken += 1
        else:
            rows.append(parsed)
    return rows, broken


def load_state(path: Path) -> dict:
    if not path.exists():
        return json.loads(json.dumps(_DEFAULT_STATE))
    with path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)
    for key, value in _DEFAULT_STATE.items():
        state.setdefault(key, json.loads(json.dumps(value)))
    return state


def update_state(path: Path, fn: Callable[[dict], None]) -> dict:
    """Read, modify, and atomically replace under an exclusive lock."""
    with lock_file(path):
        state = load_state(path)
        fn(state)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return state


def next_task_id(path: Path) -> str:
    box: dict[str, int] = {}

    def bump(state: dict) -> None:
        state["task_counter"] = int(state.get("task_counter", 0)) + 1
        box["n"] = state["task_counter"]

    update_state(path, bump)
    return f"T-{box['n']:04d}"
