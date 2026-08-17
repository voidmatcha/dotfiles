"""Read-only web view.

Lets the vault be viewed in a browser. No syncing is needed, so no copy of the
vault ends up on another machine. The point of this approach is that when you
read personal records on a company device, nothing is left on that disk.

There is no write path. Only GET is served; POST/PUT/DELETE are refused with 405.
The default bind is 127.0.0.1, and external exposure is delegated to Tailscale
Serve (the same security posture as the local-preview-server skill).
"""

from __future__ import annotations

import html
import importlib.util
import re
import sys
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

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


vaultio, queries = _load("vaultio"), _load("queries")

STYLE = """
:root { color-scheme: light dark; --fg:#1a1a1a; --bg:#fff; --dim:#666;
        --line:#e2e2e2; --accent:#2b6cb0; --warn:#b7791f; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8e8; --bg:#16181a; --dim:#9aa0a6; --line:#2c3034;
          --accent:#7aa7d9; --warn:#d9a84a; } }
* { box-sizing: border-box; }
body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
       font:16px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
       max-width:52rem; margin-inline:auto; overflow-wrap:anywhere; }
h1 { font-size:1.5rem; margin:0 0 1.5rem; }
h2 { font-size:1.15rem; margin:2rem 0 .6rem; padding-bottom:.3rem;
     border-bottom:1px solid var(--line); }
h3 { font-size:1rem; margin:1.4rem 0 .4rem; color:var(--dim); font-weight:600; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
nav { margin-bottom:2rem; font-size:.9rem; }
nav a { margin-right:1rem; }
ul { padding-left:1.2rem; }
li { margin:.2rem 0; }
code { background:var(--line); padding:.1rem .3rem; border-radius:3px; font-size:.9em; }
pre { background:var(--line); padding:.7rem .9rem; border-radius:6px; overflow-x:auto; }
pre code { background:none; padding:0; font-size:.85em; line-height:1.5; }
table { border-collapse:collapse; width:100%; margin:.5rem 0; font-size:.92rem;
        display:block; overflow-x:auto; }
th,td { border:1px solid var(--line); padding:.35rem .6rem; text-align:left;
        white-space:nowrap; }
th { background:var(--line); }
.dim { color:var(--dim); font-size:.88rem; }
.warn { color:var(--warn); }
.empty { color:var(--dim); font-style:italic; }
.card { border:1px solid var(--line); border-radius:6px; padding:.7rem .9rem;
        margin:.5rem 0; }
.card b { font-weight:600; }
"""

# Characters allowed in a page name. Path separators, .., and a leading dot are
# all excluded. Spaces are allowed: titles like "아스테로이드 시티" actually
# exist, and blocking them makes just that note quietly 404. Path separators are
# still left out, and the last line of defense is resolve_page's is_relative_to
# check.
_SAFE_NAME = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣._ ,()-]*")

# Folders the web view serves. tasks uses its own prefix glob.
_PAGE_DIRS = ("projects", "library", "rest", "concepts", "records", "jobs", "companies")

_INLINE = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    # *** is matched before **. The ** pattern is [^*]+, so it cannot match
    # ***x*** at all; the user found the asterisks left showing as literal text.
    (re.compile(r"\*\*\*([^*]+)\*\*\*"), r"<b><i>\1</i></b>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<b>\1</b>"),
)

# Body text extracted by defuddle backslash-escapes markdown special characters.
# Without unescaping, \[NASDAQ: BKNG\] or \*\*\* shows up on screen verbatim.
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~])")

# External links. The scheme is pinned to http/https in the regex itself. Rather
# than checking a whitelist afterwards, not matching at all means something like
# javascript: never becomes a link and just stays as text. This function runs
# html.escape first, so quotes inside a URL are already &quot; and cannot leak
# out of the attribute.
_LINK = re.compile(r"\[([^\[\]]+)\]\((https?://[^\s)]+)\)")


def _inline(text: str, link: bool = True) -> str:
    out = _ESCAPED.sub(r"\1", html.escape(text))
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    if link:
        # Strip embeds (![[x]]) first. They are Obsidian-only syntax and cannot be
        # rendered here. Left alone, only the '!' remained and it became a broken
        # link, which the user found. A .base is not even markdown, so turning it
        # into a link would 404.
        out = re.sub(
            r"!\[\[([^\]|]+)\]\]",
            lambda m: f'<p class="empty">[{m.group(1)}] — 옵시디언에서 표로 보인다</p>',
            out,
        )
        # Wikilinks are handled first so [[x]] does not hit the external link
        # pattern. The aliased form ([[path|label]]) is matched first: the pattern
        # below excludes |, so aliased links went unmatched and stayed as raw
        # text, which the user found.
        out = re.sub(
            r"\[\[([^\]|]+)\|([^\]]+)\]\]",
            lambda m: f'<a href="/page/{quote(m.group(1))}">{m.group(2)}</a>',
            out,
        )
        out = re.sub(
            r"\[\[([^\]|]+)\]\]",
            lambda m: f'<a href="/page/{quote(m.group(1))}">{m.group(1)}</a>',
            out,
        )
        out = _LINK.sub(
            lambda m: f'<a href="{m.group(2)}" target="_blank" '
                      f'rel="noopener noreferrer">{m.group(1)}</a>',
            out,
        )
    return out


def markdown(text: str) -> str:
    """Handle only the subset the vault produces. Not a general markdown parser."""
    out: list[str] = []
    in_list = in_table = False
    fence: list[str] | None = None

    def close() -> None:
        nonlocal in_list, in_table
        if in_list:
            out.append("</ul>")
            in_list = False
        if in_table:
            out.append("</table>")
            in_table = False

    for raw in text.split("\n"):
        line = raw.rstrip()
        # Code fences. The inside is preserved as is, not parsed as markdown.
        # Formulas and diagrams go in here, and flowing them into paragraphs
        # destroys every line break and space alignment.
        if line.lstrip().startswith("```"):
            if fence is None:
                close()
                fence = []
            else:
                out.append("<pre><code>" + html.escape("\n".join(fence)) + "</code></pre>")
                fence = None
            continue
        if fence is not None:
            fence.append(raw)
            continue
        if not line.strip():
            close()
            continue
        if line.startswith("<!--"):
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            close()
            level = min(len(heading.group(1)) + 1, 4)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if not in_table:
                close()
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
                continue
            out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if line.startswith("- "):
            if not in_list:
                close()
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            continue
        close()
        out.append(f"<p>{_inline(line)}</p>")
    # An unclosed fence is not thrown away either. Losing content is the worst case.
    if fence:
        out.append("<pre><code>" + html.escape("\n".join(fence)) + "</code></pre>")
    close()
    return "\n".join(out)


def _shell(title: str, body: str) -> bytes:
    return (
        "<!doctype html><html lang=ko><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>"
        '<nav><a href="/">상태</a><a href="/index">전체 목록</a>'
        '<a href="/page/dashboard">대시보드</a>'
        '<a href="/concepts">개념</a><a href="/library">자료</a>'
        '<a href="/records">기록</a><a href="/jobs">공고</a>'
        '<a href="/companies">회사</a><a href="/rest">쉴 때</a>'
        '<a href="/todo">확인 대기</a></nav>'
        f"{body}</body></html>"
    ).encode("utf-8")


def _status_html(home: Path, vault: Path, cfg) -> str:
    result = queries.status(home, vault, cfg)
    parts = ["<h1>llmwiki</h1>"]
    for label, key, warn in (
        ("정체 경고", "stale", True),
        ("진행 중", "doing", False),
        ("대기 큐", "queued", False),
    ):
        rows = result[key]
        cls = ' class="warn"' if warn and rows else ""
        parts.append(f"<h2{cls}>{label} <span class=dim>{len(rows)}</span></h2>")
        if not rows:
            parts.append('<p class="empty">없음</p>')
            continue
        for task in rows:
            tid = html.escape(str(task.get("id", "")))
            parts.append(
                f'<div class=card><a href="/page/{tid}"><b>{tid}</b></a> '
                f'{html.escape(str(task.get("title", "")))}'
                f'<div class=dim>{html.escape(str(task.get("project", "")))} · '
                f'마지막 {html.escape(str(task.get("last_active") or "없음"))}</div></div>'
            )
    events_file = home / "events.ndjson"
    if events_file.exists():
        stamp = time.strftime("%H:%M:%S", time.localtime(events_file.stat().st_mtime))
        parts.append(f'<p class=dim>데이터 갱신 {stamp}</p>')
    activity = queries.activity(home, cfg)
    if activity:
        parts.append(f"<h2>프로젝트 활동 <span class=dim>최근 {cfg.unclassified_days}일</span></h2>")
        parts.append("<table><tr><th>프로젝트</th><th>세션</th><th>미분류</th><th>마지막</th></tr>")
        for row in activity:
            slug = html.escape(row["project"])
            parts.append(
                f'<tr><td><a href="/page/{slug}">{slug}</a></td><td>{row["sessions"]}</td>'
                f'<td>{row["unclassified"]}</td><td>{html.escape(row["last"][5:10])}</td></tr>'
            )
        parts.append("</table>")
    return "".join(parts)


_STATUS_LABEL = {"todo": "할 것", "doing": "하는 중",
                 "done": "한 것", "dropped": "접음",
                 "wip": "정리 중"}

# Folders the web view gives a listing page. They are not put on the status
# screen - the main page is for looking at work state, and mixing reading
# material in there blurs what it is for.
_FOLDER_PAGES = {"concepts": "개념 정리", "library": "가져온 자료",
                 "records": "기록", "rest": "쉴 때 할 것",
                 "jobs": "채용 공고", "companies": "회사"}

# Undecided items. Scattered across notes, nobody ends up looking at them. It
# uses the plain markdown checkbox, so a click closes it in Obsidian too. Only
# open ones are gathered.
_TODO = re.compile(r"^\s*[-*]\s*\[ \]\s*(.+?)\s*$", re.MULTILINE)


def todo_html(vault: Path) -> str:
    rows: list[tuple[str, str, list[str]]] = []
    total = 0
    for folder in ("",) + tuple(_PAGE_DIRS):
        root = vault / folder if folder else vault
        if not root.is_dir():
            continue
        for page in sorted(root.glob("*.md")):
            items = _TODO.findall(page.read_text(encoding="utf-8"))
            if not items:
                continue
            rows.append((page.stem, folder or ".", items))
            total += len(items)
    parts = [f"<h1>확인 대기 <span class=dim>{total}</span></h1>"]
    if not rows:
        parts.append('<p class="empty">열린 항목 없음</p>')
        return "".join(parts)
    parts.append('<p class=dim>확정되면 노트에서 체크하면 여기서 사라진다.</p>')
    for stem, folder, items in rows:
        parts.append(
            f'<h2><a href="/page/{quote(stem)}">{html.escape(stem)}</a> '
            f'<span class=dim>{html.escape(folder)} · {len(items)}</span></h2><ul>'
        )
        parts.extend(f"<li>{_inline(i)}</li>" for i in items)
        parts.append("</ul>")
    return "".join(parts)


def _folder_html(vault: Path, folder: str) -> str:
    """Lay one folder out as a table.

    A base (.base) renders only in Obsidian. Without a listing in the web view
    there is no way in but typing the URL by hand, and that is exactly why these
    were not visible.
    """
    title = _FOLDER_PAGES.get(folder, folder)
    root = vault / folder
    rows = []
    if root.is_dir():
        for page in sorted(root.glob("*.md")):
            meta, _ = vaultio.read_page(page)
            rows.append((page.stem, meta))
    parts = [f"<h1>{html.escape(title)} <span class=dim>{len(rows)}</span></h1>"]
    if not rows:
        parts.append('<p class="empty">없음</p>')
        return "".join(parts)
    parts.append("<table><tr><th>제목</th><th>종류</th><th>상태</th></tr>")
    for stem, meta in rows:
        state = str(meta.get("status") or "")
        kind = str(meta.get("kind") or meta.get("domain") or meta.get("type") or "")
        parts.append(
            f'<tr><td><a href="/page/{quote(stem)}">{html.escape(stem)}</a></td>'
            f"<td>{html.escape(kind)}</td>"
            f"<td>{html.escape(_STATUS_LABEL.get(state, state))}</td></tr>"
        )
    parts.append("</table>")
    return "".join(parts)


def resolve_page(vault: Path, name: str) -> Path | None:
    """Return only markdown inside the vault. Blocks path escapes."""
    # Narrow the name first. A path separator or .. is dangerous both as a glob
    # pattern and in path assembly; glob even throws on absolute path patterns.
    #
    # Nested paths (library/jobs/<posting>/<date>) are allowed, but the separator
    # alone is not loosened. Every segment must pass the same check and the first
    # segment is restricted to a known folder. Loosening the check wholesale would
    # reopen the escape route.
    segments = (name or "").split("/")
    if not all(_SAFE_NAME.fullmatch(seg) for seg in segments):
        return None
    root = vault.resolve()
    if len(segments) > 1:
        if segments[0] not in _PAGE_DIRS:
            return None
        candidates = [root.joinpath(*segments[:-1]) / f"{segments[-1]}.md"]
    else:
        name = segments[0]
        tasks_dir = root / "tasks"
        candidates = [root / f"{name}.md"]
        candidates += [root / folder / f"{name}.md" for folder in _PAGE_DIRS]
        if tasks_dir.is_dir():
            candidates.extend(sorted(tasks_dir.glob(f"{name}*.md")))
    for candidate in candidates:
        try:
            target = candidate.resolve()
        except OSError:
            continue
        if target.is_file() and target.suffix == ".md" and target.is_relative_to(root):
            return target
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "llmwiki"

    def __init__(self, *args, home: Path, vault: Path, cfg, **kwargs):
        self._home, self._vault, self._cfg = home, vault, cfg
        super().__init__(*args, **kwargs)

    def log_message(self, *args) -> None:  # do not spill access logs to stderr
        pass

    def _send(self, payload: bytes, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/":
            self._send(_shell("llmwiki", _status_html(self._home, self._vault, self._cfg)))
            return
        if path == "/index":
            page = self._vault / "index.md"
            text = page.read_text(encoding="utf-8") if page.exists() else "# index\n\n_비어 있음_"
            body = re.sub(
                r"- (projects|tasks)/([^\s]+)\.md",
                lambda m: f"- [[{m.group(2).split('-')[0] if m.group(1) == 'tasks' else m.group(2)}]]",
                text,
            )
            self._send(_shell("전체 목록", markdown(body)))
            return
        if path == "/todo":
            self._send(_shell("확인 대기", todo_html(self._vault)))
            return
        if path.lstrip("/") in _FOLDER_PAGES:
            folder = path.lstrip("/")
            self._send(_shell(_FOLDER_PAGES[folder], _folder_html(self._vault, folder)))
            return
        if path.startswith("/page/"):
            target = resolve_page(self._vault, path[len("/page/"):])
            if target is None:
                self._send(_shell("없음", "<h1>없는 문서</h1>"), 404)
                return
            _, body = vaultio.read_page(target)
            out = f"<h1>{html.escape(target.stem)}</h1>{markdown(body)}"
            # Append the Korean translation below the English original. Mixing
            # the translation into the original file makes job-watch's change
            # detection report 'changed' every time.
            ko = target.parent / "ko" / target.name
            if ko.is_file():
                _, ko_body = vaultio.read_page(ko)
                out += ('<hr><p class=dim>아래는 한국어 번역이다. 원문이 기준이다.</p>'
                        + markdown(ko_body))
            self._send(_shell(target.stem, out))
            return
        self._send(_shell("없음", "<h1>없는 경로</h1>"), 404)

    def _reject(self) -> None:
        self._send(_shell("거절", "<h1>읽기 전용</h1>"), 405)

    do_POST = do_PUT = do_DELETE = do_PATCH = _reject


def _refresher(home: Path, seconds: int) -> None:
    """Incrementally import from claude-mem on a schedule.

    ingest only appends to events.ndjson and never touches the vault. That makes
    it safe even with Obsidian open, and fine to run often. The only thing that
    writes the vault is compile, and that runs only at night.
    """
    ingest = _load("ingest")
    db = Path.home() / ".claude-mem" / "claude-mem.db"
    while True:
        time.sleep(seconds)
        try:
            if db.exists():
                ingest.run(home, db)
        except Exception as exc:  # a refresh failure must not kill the server
            print(f"refresh 실패: {exc}", file=sys.stderr, flush=True)


def serve(home: Path, vault: Path, cfg, bind: str = "127.0.0.1", port: int = 8391,
          refresh: int = 60) -> None:
    if refresh > 0:
        threading.Thread(target=_refresher, args=(home, refresh), daemon=True).start()
    handler = partial(Handler, home=home, vault=vault, cfg=cfg)
    with ThreadingHTTPServer((bind, port), handler) as httpd:
        print(f"llmwiki 읽기 전용 서버: http://{bind}:{port}", flush=True)
        print(f"  자동 갱신: {refresh}초마다 ingest" if refresh > 0 else "  자동 갱신 없음",
              flush=True)
        if bind == "127.0.0.1":
            print(f"  tailnet 노출: tailscale serve --bg --https={port} http://127.0.0.1:{port}",
                  flush=True)
        httpd.serve_forever()
