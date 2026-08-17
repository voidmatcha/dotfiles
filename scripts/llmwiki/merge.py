from __future__ import annotations

LAST_WINS = ("next_steps", "learned", "completed", "investigated", "notes", "harness",
             # Which directory an item collected under unfiled originally came
             # from. Lose this and there is no basis to pull it out via mapping.
             "origin")


def by_session_project(events: list[dict]) -> list[dict]:
    """Fold by (session, project) pair. One session can move across projects."""
    buckets: dict[tuple[str, str], list[dict]] = {}
    for event in events:
        buckets.setdefault((event["session_id"], event["project"]), []).append(event)

    merged: list[dict] = []
    for (session_id, project), group in buckets.items():
        group.sort(key=lambda e: (e["at"], e["event_id"]))
        first, last = group[0], group[-1]
        row = {
            "session_id": session_id,
            "project": project,
            "at": last["at"],
            "request": first.get("request", ""),
            "merged_from": len(group),
        }
        row.update({key: last.get(key, "") for key in LAST_WINS})
        for key in ("files_read", "files_edited"):
            row[key] = sorted({p for e in group for p in e.get(key, [])})
        merged.append(row)

    merged.sort(key=lambda r: (r["at"], r["session_id"], r["project"]))
    return merged
