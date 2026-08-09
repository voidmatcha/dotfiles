"""실패한 시도 후보를 뽑고, 승인된 교훈을 프로젝트 노트에 적는다.

두 단계로 나뉜다. 여기(기계)는 재현율을 목표로 후보를 넓게 건지고, 정밀도는
사람 또는 세션의 LLM 이 맡는다. 키워드만으로 '실패한 시도'와 '남의 버그를
고친 작업'을 가를 수 없다. 실제 요약문에서 "테스트 실패를 고쳤다"와 "내가
깨뜨려서 되돌렸다"는 같은 단어를 쓴다.

쓰는 위치가 GEN 마커 바깥이라 compile 이 덮어쓰지 않는다. 그래서 승인은
한 번만 일어나야 하고, 중복 제안을 막는 근거는 lessons.ndjson 에 남긴다.
노트에서 사람이 지운 교훈이 다시 후보로 올라오면 안 된다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime, timezone
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


store, queries, vaultio = _load("store"), _load("queries"), _load("vaultio")

HEADING = "## 실패한 시도 (다시 하지 말 것)"
LEDGER = "lessons.ndjson"

# 가중치 2는 "내가 뭔가를 망가뜨렸다"에 가까운 말, 1은 정황 증거다. 한국어와
# 영어를 같이 본다. claude-mem 요약은 두 언어가 섞여 나온다.
_SIGNALS: tuple[tuple[str, int], ...] = (
    ("되돌", 2), ("롤백", 2), ("rollback", 2), ("revert", 2),
    ("깨뜨", 2), ("깨먹", 2), ("깨졌", 2), ("깨진", 2),
    ("broke", 2), ("broken", 2),
    ("복구", 2), ("restore", 2), ("회귀", 2), ("regression", 2),
    ("하지 말", 2), ("데이터 손실", 2), ("data loss", 2),
    ("잘못", 1), ("실패", 1), ("fail", 1),
    ("재시도", 1), ("retry", 1), ("다시 시도", 1),
    ("착각", 1), ("오해", 1), ("misunderstood", 1), ("mistake", 1),
    ("함정", 1), ("trap", 1), ("놓쳤", 1), ("missed", 1),
    ("삽질", 1), ("무의미", 1), ("헛", 1),
    ("false", 1), ("틀렸", 1), ("wrong", 1),
)

_FIELDS = ("learned", "investigated", "completed", "notes", "next_steps")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ref_of(session_id: str) -> str:
    """볼트 타임라인이 이미 쓰는 8자 접두사를 그대로 쓴다."""
    return session_id[:8]


def score(row: dict) -> tuple[int, list[str]]:
    blob = " ".join(str(row.get(f) or "") for f in _FIELDS).lower()
    hits, total = [], 0
    for term, weight in _SIGNALS:
        if term in blob:
            hits.append(term)
            total += weight
    return total, hits


def ledger(home: Path) -> dict[tuple[str, str], dict]:
    """(session_id, project) -> 마지막 판정. 승인도 기각도 재제안을 막는다."""
    rows, _ = store.read_json(home / LEDGER)
    rows.sort(key=lambda r: r.get("at", ""))
    view: dict[tuple[str, str], dict] = {}
    for row in rows:
        view[(row.get("session_id", ""), row.get("project", ""))] = row
    return view


def candidates(home: Path, cfg, vault: Path | None = None,
               project: str | None = None, days: int | None = None,
               min_score: int = 2, limit: int = 20) -> list[dict]:
    """점수는 순위용 눈금일 뿐 정밀도가 아니다.

    긴 요약일수록 더 많은 신호에 걸리므로 점수에는 길이 편향이 있다. 그래서
    동점 처리는 최신순으로 하고, 진짜 판별은 호출자(사람 또는 세션의 LLM)가
    본문을 읽고 한다. 노트가 없는 프로젝트는 accept 가 실패하므로 걸러내되,
    몇 건을 걸렀는지는 note_exists 로 드러내고 조용히 감추지 않는다.
    """
    decided = ledger(home)
    cutoff = queries._cutoff(days) if days else None
    out: list[dict] = []
    for row in queries._merged(home, cfg):
        if project and row["project"] != project:
            continue
        if cutoff and row["at"] < cutoff:
            continue
        if (row["session_id"], row["project"]) in decided:
            continue
        total, hits = score(row)
        if total < min_score:
            continue
        exists = True
        if vault is not None:
            exists = (vault / "projects" / f'{row["project"]}.md').exists()
        out.append({
            "ref": ref_of(row["session_id"]),
            "session_id": row["session_id"],
            "project": row["project"],
            "at": row["at"],
            "score": total,
            "signals": hits,
            "note_exists": exists,
            "request": row.get("request", ""),
            "learned": row.get("learned", ""),
            "investigated": row.get("investigated", ""),
            "completed": row.get("completed", ""),
        })
    # 안정 정렬 두 번으로 (점수 내림, 날짜 내림)을 만든다.
    out.sort(key=lambda r: r["at"], reverse=True)
    out.sort(key=lambda r: -r["score"])
    return out[:limit]


def resolve(home: Path, cfg, ref: str) -> dict:
    """접두사 하나로 후보를 특정한다. 애매하면 세우지 말고 멈춘다."""
    hits = [c for c in candidates(home, cfg, min_score=0, limit=10_000)
            if c["session_id"].startswith(ref)]
    if not hits:
        raise KeyError(f"{ref} 에 해당하는 미판정 후보가 없다")
    if len(hits) > 1:
        names = ", ".join(f'{h["ref"]}({h["project"]})' for h in hits[:5])
        raise KeyError(f"{ref} 가 {len(hits)}건에 걸린다: {names}")
    return hits[0]


def _insert(body: str, line: str) -> str:
    """실패한 시도 절 끝에 붙인다. 다음 절이나 GEN 마커 직전이 경계다."""
    start = body.find(HEADING)
    if start < 0:
        raise ValueError(f"{HEADING} 절이 없다")
    after = start + len(HEADING)
    rest = body[after:]
    stop = len(rest)
    for pattern in (r"^## ", r"^<!-- GEN:"):
        found = re.search(pattern, rest, re.MULTILINE)
        if found and found.start() < stop:
            stop = found.start()
    section = rest[:stop].rstrip("\n")
    section = f"{section}\n{line}" if section.strip() else f"\n\n{line}"
    return body[:after] + section + "\n\n" + rest[stop:]


def accept(home: Path, vault: Path, cand: dict, text: str) -> Path:
    text = " ".join(text.split())
    if not text:
        raise ValueError("교훈 문장이 비어 있다")
    page = vault / "projects" / f'{cand["project"]}.md'
    if not page.exists():
        raise FileNotFoundError(f"{page} 가 없다. compile 을 먼저 돌려라")
    meta, body = vaultio.read_page(page)
    day = cand["at"][:10]
    line = f'- [{day}] {text} <!-- ref:{cand["ref"]} -->'
    vaultio.write_page(page, meta, _insert(body, line))
    store.append_json(home / LEDGER, {
        "session_id": cand["session_id"], "project": cand["project"],
        "ref": cand["ref"], "action": "accepted", "text": text, "at": _now(),
    })
    return page


def dismiss(home: Path, cand: dict, reason: str = "") -> None:
    store.append_json(home / LEDGER, {
        "session_id": cand["session_id"], "project": cand["project"],
        "ref": cand["ref"], "action": "dismissed", "reason": reason, "at": _now(),
    })


def render(rows: list[dict], max_chars: int = 700) -> str:
    if not rows:
        return "후보 없음"
    out = []
    for row in rows:
        head = f'[{row["ref"]}] {row["project"]}  {row["at"][:10]}  score {row["score"]}'
        signals = ", ".join(row["signals"][:6])
        blob = " / ".join(
            str(row.get(f) or "").strip()
            for f in ("learned", "investigated", "completed")
            if str(row.get(f) or "").strip()
        )
        if len(blob) > max_chars:
            blob = blob[:max_chars] + "…"
        out.append(f"{head}\n    신호: {signals}\n    {blob}")
    return "\n\n".join(out)
