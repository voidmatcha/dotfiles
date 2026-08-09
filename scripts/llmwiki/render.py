from __future__ import annotations


def _clip(text: str, limit: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:limit]


def _head(row: dict) -> str:
    return f"{row['at'][5:10]} {row.get('harness', '?')} {row['session_id'][:8]}"


def progress_line(row: dict, truncate_request: int, truncate_next: int) -> str:
    flag = f" (요약 {row['merged_from']}건 압축)" if row.get("merged_from", 1) > 1 else ""
    lines = [f"### [{_head(row)}]{flag}"]
    if row.get("request"):
        lines.append(f"- 시작: {_clip(row['request'], truncate_request)}")
    if row.get("next_steps"):
        lines.append(f"- 다음: {_clip(row['next_steps'], truncate_next)}")
    if row.get("files_edited"):
        lines.append("- 파일: " + ", ".join(row["files_edited"][:5]))
    return "\n".join(lines)


def timeline_line(row: dict, task_id: str | None) -> str:
    suffix = f" [[{task_id}]]" if task_id else ""
    # unfiled 항목은 원래 디렉터리를 함께 보여준다. 그것만이 이 줄을 제
    # 프로젝트로 되돌릴 단서다.
    origin = f" ({row['origin']})" if row.get("origin") else ""
    return f"- [{_head(row)}]{origin} {_clip(row.get('request', ''), 90)}{suffix}"
