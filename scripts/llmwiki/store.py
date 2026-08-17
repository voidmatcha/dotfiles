from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Callable

_DEFAULT_STATE = {"watermark": {}, "task_counter": 0, "version": 1}


def append_json(path: Path, obj: dict) -> None:
    """Append one line with a single O_APPEND write; concurrent appends never clash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_json(path: Path) -> tuple[list[dict], int]:
    """Skip broken lines, counting them. A last line left half-written is common."""
    if not path.exists():
        return [], 0
    rows: list[dict] = []
    broken = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                broken += 1
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
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            state = load_state(path)
            fn(state)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
            return state
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def next_task_id(path: Path) -> str:
    box: dict[str, int] = {}

    def bump(state: dict) -> None:
        state["task_counter"] = int(state.get("task_counter", 0)) + 1
        box["n"] = state["task_counter"]

    update_state(path, bump)
    return f"T-{box['n']:04d}"
