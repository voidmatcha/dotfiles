from __future__ import annotations

LAST_WINS = ("next_steps", "learned", "completed", "investigated", "notes", "harness",
             # unfiled 로 모인 항목이 원래 어느 디렉터리에서 왔는지. 이걸
             # 잃으면 mapping 으로 꺼낼 근거가 사라진다.
             "origin")


def by_session_project(events: list[dict]) -> list[dict]:
    """(세션, 프로젝트) 쌍으로 접는다. 세션 하나가 여러 프로젝트를 오갈 수 있다."""
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
