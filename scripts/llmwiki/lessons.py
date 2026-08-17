"""Pick 실패한 시도 candidates and write accepted lessons into the project note.

This splits into two stages. Here (the machine) casts a wide net for recall, and
precision is left to a human or the session's LLM. Keywords alone cannot separate
a 실패한 시도 from work that fixed somebody else's bug. In real summaries, "fixed
the failing test" and "I broke it and reverted" use the same words.

What gets written sits outside the GEN markers, so compile does not overwrite it.
That means acceptance must happen exactly once, and the record that blocks a
duplicate proposal is kept in lessons.ndjson. A lesson a human deleted from the
note must never come back up as a candidate.
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

# Weight 2 is wording close to "I broke something", 1 is circumstantial evidence.
# Korean and English are matched together. claude-mem summaries come out with the
# two languages mixed.
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
    """Reuse the same 8-character prefix the vault timeline already uses."""
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
    """(session_id, project) -> last verdict. Accept and dismiss both block reuse."""
    rows, _ = store.read_json(home / LEDGER)
    rows.sort(key=lambda r: r.get("at", ""))
    view: dict[tuple[str, str], dict] = {}
    for row in rows:
        view[(row.get("session_id", ""), row.get("project", ""))] = row
    return view


def candidates(home: Path, cfg, vault: Path | None = None,
               project: str | None = None, days: int | None = None,
               min_score: int = 2, limit: int = 20) -> list[dict]:
    """The score is only a ranking scale, not precision.

    Longer summaries hit more signals, so the score carries a length bias. Ties
    are therefore broken by recency, and the real judgment is made by the caller
    (a human or the session's LLM) reading the body. Projects with no note fail on
    accept, so they are filtered out, but how many were filtered is exposed
    through note_exists rather than quietly hidden.
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
    # Two stable sorts produce (score descending, date descending).
    out.sort(key=lambda r: r["at"], reverse=True)
    out.sort(key=lambda r: -r["score"])
    return out[:limit]


def resolve(home: Path, cfg, ref: str) -> dict:
    """Pin down one candidate by prefix. If ambiguous, stop instead of guessing."""
    hits = [c for c in candidates(home, cfg, min_score=0, limit=10_000)
            if c["session_id"].startswith(ref)]
    if not hits:
        raise KeyError(f"{ref} 에 해당하는 미판정 후보가 없다")
    if len(hits) > 1:
        names = ", ".join(f'{h["ref"]}({h["project"]})' for h in hits[:5])
        raise KeyError(f"{ref} 가 {len(hits)}건에 걸린다: {names}")
    return hits[0]


def _insert(body: str, line: str) -> str:
    """Append at end of the 실패한 시도 section. Bound by next section or GEN marker."""
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
