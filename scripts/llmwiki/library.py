"""Imported material (Library). Kept apart from my own work (projects/).

raw/ is where things get dumped and library/ holds the wiki-ified notes. The
original is never deleted. If the note replaced the original, there would be
nothing to trace back to when the summary turns out to be wrong.

This too does only the machine's share: find the files, filter duplicates, stand
up empty notes. The summary and the links are filled in by the session's LLM.
That is the boundary that keeps an LLM out of the nightly job, and the device
that stops unverified summaries from piling up automatically.
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

# Things Obsidian would not mistake for notes, plus the litter macOS leaves.
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
    """(sha -> note, source path -> note).

    Both indexes are needed. sha catches the same content dumped again, source
    catches the same original being edited. Without the latter, fixing a single
    typo creates one more note, and the summary written first stays behind
    describing the old content.
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
    """Stand up an empty library note for each new file in raw/."""
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
            # The original changed. The summary may be stale, but human-written
            # prose is never discarded automatically. Just report it and leave the
            # resync decision to the caller.
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
    """Put a note whose original changed back up for review.

    Only sha is refreshed and status drops to pending. The human-written summary
    is not deleted. Deleting it turns a job of patching just the changed part into
    a job of writing the whole thing from scratch.
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
    """Record the source address. Where it came from outlives the source itself.

    It is never filled in automatically. Guessing the origin of pasted text can be
    wrong, and a wrong origin is worse than no origin. The person who verified it
    puts it in.
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
    """Check the summary section holds real prose. Passing a heading-only note to
    done empties the pending list falsely and grows the wiki with empty shells."""
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
