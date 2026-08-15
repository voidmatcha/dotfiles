#!/usr/bin/env python3
"""Detect closures and changes in job postings. Judgement fields are left alone.

Fields the machine writes: checked, status (only ever to closed), closed_reason,
changed_on.
Fields the human writes: fit, status (everything else), the gap analysis in the
body — never modified here.

Mistaking a network error for a closure turns a live posting into a dead one.
So a failure is only logged, and the note is left unchanged.
"""
from __future__ import annotations

import argparse
import re
import pathlib
import subprocess
import sys
from datetime import date
from pathlib import Path

REQUIRED = ("type", "title", "company", "status", "track", "source", "source_kind", "checked")
SKIP_KINDS = {"linkedin", "referral", "newsletter"}
FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse_fm(text: str) -> dict[str, str]:
    m = FM.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).split("\n"):
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"')
    return out


def set_fm(text: str, key: str, value: str) -> str:
    """Update a frontmatter key. If it is absent, insert it before updated."""
    if re.search(rf"^{key}:", text, re.M):
        return re.sub(rf"^{key}:.*$", f"{key}: {value}", text, count=1, flags=re.M)
    return re.sub(r"^updated:", f"{key}: {value}\nupdated:", text, count=1, flags=re.M)


def fetch(url: str) -> tuple[str | None, str]:
    """(body, reason). A body of None means the note must not be changed."""
    try:
        r = subprocess.run(
            ["defuddle", "parse", url, "--md"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return None, "defuddle 미설치"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    err = (r.stderr or "").lower()
    if "404" in err or "not found" in err or "410" in err:
        code = http_status(url)
        if code in (404, 410):
            return "", f"gone (HTTP {code})"
        return None, f"defuddle 은 404 라 했으나 실제 HTTP {code or '확인 불가'}. 보류"
    if r.returncode != 0 or not r.stdout.strip():
        # An extraction failure is indistinguishable from a deleted page here.
        # Do not conclude that the posting is closed.
        return None, (r.stderr or "빈 응답").strip()[:120]
    return r.stdout, "ok"


def link_snapshot(text: str, slug: str, url: str, day: str) -> str:
    """Keep the note's ## 원본 section up to date.

    The posting URL must always be there, even when there is no snapshot.
    Closed postings and postings whose capture failed have no snapshot, and the
    user found that in exactly those cases the body offered no route back to the
    original. Inserting the link by hand goes stale at the next snapshot.
    """
    label = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    lines = [f"- [공고 페이지]({url})" if url.startswith("http") else "- 공고 URL 없음"]
    snapdir = pathlib.Path(SNAP_ROOT) / slug
    if snapdir.is_dir():
        for x in sorted((f.stem for f in snapdir.glob("*.md")), reverse=True):
            lines.append(f"- [[library/jobs/{slug}/{x}|수집 {x}]]")
    block = "## 원본\n\n" + "\n".join(lines) + "\n"
    if "## 원본" in text:
        return re.sub(r"## 원본\n\n(?:- .*\n)*", block, text, count=1)
    if "## 연결" in text:
        return re.sub(r"^## 연결", block + "\n## 연결", text.rstrip("\n"), count=1, flags=re.M) + "\n"
    return text.rstrip("\n") + "\n\n" + block


SENTINEL = "<!--원문-->"
SNAP_ROOT = "library/jobs"


def wrap(body: str, slug: str, url: str, day: str) -> str:
    """Attach a provenance header to the snapshot.

    Without the header there is no way to tell which posting this file belongs
    to, or where the original lives. Comparison only looks below SENTINEL, so the
    header never disturbs change detection.
    """
    label = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    return (f"> **원본** [{label}]({url})\n"
            f"> **수집** {day} · [[{slug}]]\n\n"
            f"{SENTINEL}\n{body}")


def content_of(text: str) -> str:
    """Strip a snapshot down to the original body. Files in the pre-header
    format (no header at all) are accepted too."""
    return text.split(SENTINEL, 1)[-1] if SENTINEL in text else text


def http_status(url: str) -> int:
    """Confirm the real HTTP status through an independent request.

    Concluding that a posting is closed just because defuddle returned 404 once
    lets a transient error permanently kill a live posting. The user found a live
    posting that had been closed by exactly such a one-off 404. Close only when
    both signals agree the page is gone.
    """
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "-L", "--max-time", "25", url],
            capture_output=True, text=True, timeout=40,
        )
        return int((r.stdout or "0").strip() or 0)
    except Exception:
        return 0


# Signed image URLs get a new value on every request. The user found that one
# job board's avatar images were AWS S3 presigned URLs, which made every single
# run report the posting as 'changed'. Images are not posting content, so they
# are dropped from the comparison entirely.
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# Signature parameters left outside an image are stripped for the same reason.
_SIGNED = re.compile(r"[?&](X-Amz-[^&\s)]*|Expires|Signature)=[^&\s)]*", re.I)


# Check that what came back is actually a posting. A 200 response still turned
# out to be a job listing index or an error page three separate times. Saving
# without this check makes later diffs lie, and leaves nothing to translate.
#
# The decision leans on length and on explicit bad-page patterns. Using a keyword
# list as the primary signal misses phrasings like "What impact can you make" and
# so flags healthy postings as bad. Two healthy postings were caught that way.
_LISTING = re.compile(r"^\s*#{0,6}\s*\d{2,}\s+jobs\b", re.I | re.M)
_ERRORPAGE = re.compile(r"^>\s*\[!error\]|submission was sent successfully", re.I | re.M)
_MIN_CHARS = 700


def looks_like_posting(body: str) -> tuple[bool, str]:
    text = body.strip()
    if _ERRORPAGE.search(text):
        return False, "에러/폼 확인 페이지로 보인다"
    if _LISTING.search(text):
        return False, "채용 목록 페이지로 보인다"
    if len(text) < _MIN_CHARS:
        return False, f"본문이 너무 짧다 ({len(text)}자)"
    return True, ""


def normalize(s: str) -> str:
    """Normalize for comparison. Anything that changes per request is not a
    content change."""
    s = _IMG.sub("", s)
    s = _SIGNED.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(Path.home() / "Documents/llmwiki"))
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 보고만 한다")
    ap.add_argument("--only", help="slug 부분 일치로 대상 제한")
    args = ap.parse_args()

    vault = Path(args.vault)
    jobs = sorted((vault / "jobs").glob("*.md"))
    if args.only:
        jobs = [j for j in jobs if args.only in j.stem]
    if not jobs:
        print("대상 공고가 없다", file=sys.stderr)
        return 1

    today = date.today().isoformat()
    counts = {"ok": 0, "first": 0, "bad": 0, "changed": 0, "closed": 0, "skipped": 0, "failed": 0, "lint": 0}

    for note in jobs:
        text = note.read_text(encoding="utf-8")
        fm = parse_fm(text)
        slug = note.stem

        missing = [k for k in REQUIRED if k not in fm]
        if missing:
            print(f"  lint  {slug}: 필수 키 누락 {', '.join(missing)}")
            counts["lint"] += 1

        if fm.get("status") == "closed":
            counts["skipped"] += 1
            continue
        if fm.get("source_kind") in SKIP_KINDS:
            print(f"  skip  {slug}: source_kind={fm.get('source_kind')} (자동 확인 대상 아님)")
            counts["skipped"] += 1
            continue
        url = fm.get("source", "")
        if not url.startswith("http"):
            print(f"  skip  {slug}: source 없음")
            counts["skipped"] += 1
            continue

        body, why = fetch(url)

        if body is None:
            print(f"  FAIL  {slug}: {why} — 노트 변경 없음")
            counts["failed"] += 1
            continue

        # why has the form "gone (HTTP 404)". Comparing it with == "gone" never
        # matches, so a genuinely closed posting falls through with a 0-character
        # body and gets misreported as BAD.
        if why.startswith("gone"):
            print(f"  CLOSED {slug}: 페이지 없음 — {why}")
            counts["closed"] += 1
            if not args.dry_run:
                t = set_fm(text, "status", "closed")
                t = set_fm(t, "closed_reason", f"{why}, checked {today}")
                t = set_fm(t, "checked", today)
                t = set_fm(t, "updated", today)
                note.write_text(t, encoding="utf-8")
            continue

        snapdir = vault / "library" / "jobs" / slug
        snaps = sorted(snapdir.glob("*.md")) if snapdir.exists() else []
        latest = content_of(snaps[-1].read_text(encoding="utf-8")) if snaps else None

        ok, why = looks_like_posting(body)
        if not ok:
            print(f"  BAD   {slug}: {why} — 저장하지 않음")
            counts["bad"] = counts.get("bad", 0) + 1
            continue

        if latest is None:
            print(f"  first {slug}: 최초 스냅샷 생성")
            counts["first"] += 1
            if not args.dry_run:
                snapdir.mkdir(parents=True, exist_ok=True)
                (snapdir / f"{today}.md").write_text(wrap(body, slug, url, today), encoding="utf-8")
                t = set_fm(set_fm(text, "checked", today), "updated", today)
                note.write_text(link_snapshot(t, slug, url, today), encoding="utf-8")
            continue

        if normalize(latest) == normalize(body):
            print(f"  ok    {slug}")
            counts["ok"] += 1
            if not args.dry_run:
                note.write_text(set_fm(text, "checked", today), encoding="utf-8")
            continue

        print(f"  CHANGED {slug}: 스냅샷 추가 → library/jobs/{slug}/{today}.md")
        counts["changed"] += 1
        if not args.dry_run:
            (snapdir / f"{today}.md").write_text(wrap(body, slug, url, today), encoding="utf-8")
            t = set_fm(text, "changed_on", today)
            t = set_fm(t, "checked", today)
            t = set_fm(t, "updated", today)
            note.write_text(link_snapshot(t, slug, url, today), encoding="utf-8")

    print()
    print(f"확인 {len(jobs)}건 · 변화없음 {counts['ok']} · 최초수집 {counts['first']} · "
          f"변경 {counts['changed']} · 마감 {counts['closed']} · "
          f"건너뜀 {counts['skipped']} · 실패 {counts['failed']}"
          + (f" · 내용이상 {counts['bad']}" if counts.get("bad") else "")
          + (f" · 필수키누락 {counts['lint']}" if counts["lint"] else ""))
    if args.dry_run:
        print("(dry-run: 파일을 쓰지 않았다)")
    if counts["changed"] or counts["closed"]:
        print("→ 변경·마감 건은 갭 분석과 fit 을 사람이 다시 볼 것")
    return 0


if __name__ == "__main__":
    sys.exit(main())
