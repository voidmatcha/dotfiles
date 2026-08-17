from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).parent


def _load(name: str):
    key = f"llmwiki_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


store, config = _load("store"), _load("config")

SOURCE = "claude-mem"


def namespace_events(home: Path, host: str | None = None) -> dict:
    """Lift `claude-mem:{n}` to `claude-mem:{host}:{n}`.

    Without this migration the next ingest cannot find the watermark key, reads
    from 0 again, and since the event_id is in the new format deduplication does
    not catch it either, so everything gets imported a second time.
    """
    host = host or config.host()
    events_path = home / "events.ndjson"
    if not events_path.exists():
        return {"migrated": 0, "host": host}

    rows, broken = store.read_json(events_path)
    migrated = 0
    for row in rows:
        eid = row.get("event_id", "")
        if eid.startswith(f"{SOURCE}:") and eid.count(":") == 1:
            row["event_id"] = f"{SOURCE}:{host}:{eid.split(':', 1)[1]}"
            row.setdefault("host", host)
            migrated += 1
        else:
            row.setdefault("host", row.get("host", host))

    if migrated:
        tmp = events_path.with_suffix(".ndjson.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, events_path)

    def move(state: dict) -> None:
        old = state["watermark"].pop(SOURCE, None)
        if old is not None:
            state["watermark"][f"{SOURCE}:{host}"] = old

    store.update_state(home / "state.json", move)
    return {"migrated": migrated, "broken_skipped": broken, "host": host}
