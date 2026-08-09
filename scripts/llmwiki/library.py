"""가져온 자료(Library). 내가 한 작업(projects/)과 섞이지 않게 따로 둔다.

raw/ 는 던지는 곳이고 library/ 는 위키화된 노트다. 원본은 지우지 않는다.
노트가 원본을 대체하면 요약이 틀렸을 때 되짚을 근거가 사라진다.

여기도 기계 몫만 한다. 파일을 찾고, 중복을 걸러내고, 빈 노트를 세운다.
요약과 연결은 세션의 LLM 이 채운다. 야간 작업에 LLM 을 들이지 않기 위한
경계이자, 검증되지 않은 요약이 자동으로 쌓이지 않게 하는 장치다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import date
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


vaultio, compiler = _load("vaultio"), _load("compiler")

RAW_DIR = "raw"
LIB_DIR = "library"
PENDING, DONE = "pending", "done"

SKELETON = (
    "## 요약\n\n"
    "## 왜 담았나\n\n"
    "## 연결\n\n"
)

# 옵시디언이 노트로 오해하지 않을 것들, 그리고 macOS 가 흘리는 부산물.
_IGNORE = {".DS_Store", "Icon\r"}


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}GB"


def raw_files(vault: Path) -> list[Path]:
    root = vault / RAW_DIR
    if not root.is_dir():
        return []
    out = [
        p for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in _IGNORE and not p.name.startswith(".")
    ]
    return out


def existing(vault: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """(sha -> 노트, source 경로 -> 노트).

    두 색인이 필요하다. sha 는 같은 내용을 다시 던진 경우를, source 는 같은
    원본을 고친 경우를 잡는다. 후자를 안 보면 오타 하나 고쳤을 때 노트가
    하나 더 생기고, 먼저 쓴 요약은 옛 내용을 설명하는 채로 남는다.
    """
    root = vault / LIB_DIR
    if not root.is_dir():
        return {}, {}
    by_sha: dict[str, Path] = {}
    by_source: dict[str, Path] = {}
    for page in sorted(root.glob("*.md")):
        meta, _ = vaultio.read_page(page)
        sha, source = str(meta.get("sha") or ""), str(meta.get("source") or "")
        if sha:
            by_sha.setdefault(sha, page)
        if source:
            by_source.setdefault(source, page)
    return by_sha, by_source


def _unique_page(root: Path, slug: str) -> Path:
    page = root / f"{slug}.md"
    n = 2
    while page.exists():
        page = root / f"{slug}-{n}.md"
        n += 1
    return page


def ingest(vault: Path) -> dict:
    """raw/ 의 새 파일마다 빈 library 노트를 세운다."""
    (vault / RAW_DIR).mkdir(parents=True, exist_ok=True)
    (vault / LIB_DIR).mkdir(parents=True, exist_ok=True)
    by_sha, by_source = existing(vault)
    created, skipped, changed = [], [], []
    for src in raw_files(vault):
        sha = _digest(src)
        if sha in by_sha:
            skipped.append(str(src.relative_to(vault)))
            continue
        rel = src.relative_to(vault)
        stale = by_source.get(str(rel))
        if stale is not None:
            # 원본이 바뀌었다. 요약이 낡았을 수 있지만 사람이 쓴 글을 자동으로
            # 버리지 않는다. 알리기만 하고 resync 판단은 호출자에게 넘긴다.
            changed.append(stale.stem)
            continue
        slug = compiler.safe_slug(src.stem)
        page = _unique_page(vault / LIB_DIR, slug)
        meta = {
            "type": "library",
            "source": str(rel),
            "origin": "",
            "added": date.today().isoformat(),
            "status": PENDING,
            "sha": sha,
        }
        body = SKELETON + (
            "<!-- GEN:source -->\n"
            f"원본: [[{rel.as_posix()}]] ({_human(src.stat().st_size)}, {src.suffix or '확장자 없음'})\n"
            "<!-- /GEN:source -->\n"
        )
        vaultio.write_page(page, meta, body)
        by_sha[sha] = page
        by_source[str(rel)] = page
        created.append(str(page.relative_to(vault)))
    return {"created": created, "skipped": len(skipped), "changed": changed}


def pending(vault: Path) -> list[dict]:
    root = vault / LIB_DIR
    if not root.is_dir():
        return []
    out = []
    for page in sorted(root.glob("*.md")):
        meta, _ = vaultio.read_page(page)
        if str(meta.get("status") or PENDING) != PENDING:
            continue
        out.append({
            "slug": page.stem,
            "source": str(meta.get("source") or ""),
            "added": str(meta.get("added") or ""),
            "note": str(page.relative_to(vault)),
        })
    return out


def mark_done(vault: Path, slug: str) -> Path:
    page = vault / LIB_DIR / f"{slug}.md"
    if not page.exists():
        raise FileNotFoundError(f"{page} 가 없다")
    meta, body = vaultio.read_page(page)
    if not _filled(body):
        raise ValueError(f"{slug}: '## 요약' 이 비어 있다. 채우고 나서 done 해라")
    meta["status"] = DONE
    meta["updated"] = date.today().isoformat()
    vaultio.write_page(page, meta, body)
    return page


def resync(vault: Path, slug: str) -> dict:
    """원본이 바뀐 노트를 다시 검토 대상으로 되돌린다.

    sha 만 갱신하고 status 를 pending 으로 내린다. 사람이 쓴 요약은 지우지
    않는다. 지우면 바뀐 부분만 고치면 되는 일이 처음부터 다시 쓰는 일이 된다.
    """
    page = vault / LIB_DIR / f"{slug}.md"
    if not page.exists():
        raise FileNotFoundError(f"{page} 가 없다")
    meta, body = vaultio.read_page(page)
    src = vault / str(meta.get("source") or "")
    if not src.is_file():
        raise FileNotFoundError(f"원본 {src} 가 없다")
    before = str(meta.get("sha") or "")
    after = _digest(src)
    if before == after:
        return {"slug": slug, "changed": False}
    meta["sha"] = after
    meta["status"] = PENDING
    meta["updated"] = date.today().isoformat()
    vaultio.write_page(page, meta, body)
    return {"slug": slug, "changed": True, "was": before, "now": after}


def set_origin(vault: Path, slug: str, origin: str) -> Path:
    """원문 주소를 기록한다. 원문이 사라져도 어디서 왔는지는 남는다.

    자동으로 찾아 넣지 않는다. 붙여넣은 글의 출처 추정은 틀릴 수 있고,
    틀린 출처는 없는 출처보다 나쁘다. 확인한 사람이 넣는다.
    """
    page = vault / LIB_DIR / f"{slug}.md"
    if not page.exists():
        raise FileNotFoundError(f"{page} 가 없다")
    meta, body = vaultio.read_page(page)
    meta["origin"] = origin
    meta["updated"] = date.today().isoformat()
    vaultio.write_page(page, meta, body)
    return page


def _filled(body: str) -> bool:
    """요약 절에 실제 글이 있는지 본다. 제목만 있는 노트를 done 으로 넘기면
    pending 목록이 거짓으로 비고, 위키가 빈 껍데기로 늘어난다."""
    start = body.find("## 요약")
    if start < 0:
        return False
    rest = body[start + len("## 요약"):]
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("##") or stripped.startswith("<!-- GEN:"):
            break
        if stripped:
            return True
    return False
