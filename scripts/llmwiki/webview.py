"""읽기 전용 웹 뷰.

vault 를 브라우저로 보게 한다. 동기화가 필요 없으므로 다른 머신에 vault 사본이
생기지 않는다. 회사 장비에서 개인 기록을 볼 때 그 디스크에 아무것도 남지 않는
것이 이 방식의 요점이다.

쓰기 경로가 없다. GET 만 처리하고 POST/PUT/DELETE 는 405 로 거절한다.
기본 바인드는 127.0.0.1 이고, 외부 노출은 Tailscale Serve 에 위임한다
(local-preview-server 스킬의 보안 자세와 같다).
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

# 페이지 이름으로 허용하는 문자. 경로 구분자, .., 선행 점을 전부 배제한다.
# 공백을 허용한다. "아스테로이드 시티" 같은 제목이 실제로 있고, 막으면 그
# 노트만 조용히 404 가 된다. 경로 구분자는 여전히 빠져 있고, 최종 방어선은
# resolve_page 의 is_relative_to 검사다.
_SAFE_NAME = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣._ ,()-]*")

# 웹뷰가 넘겨줄 폴더. tasks 는 접두사 glob 을 따로 쓴다.
_PAGE_DIRS = ("projects", "library", "rest", "concepts", "records", "jobs", "companies")

_INLINE = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    # *** 를 ** 보다 먼저 본다. ** 패턴은 [^*]+ 라 ***x*** 를 아예 못 잡고
    # 별표가 글자로 남아 있던 것을 사용자가 발견했다.
    (re.compile(r"\*\*\*([^*]+)\*\*\*"), r"<b><i>\1</i></b>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<b>\1</b>"),
)

# defuddle 이 추출한 본문은 마크다운 특수문자를 백슬래시로 이스케이프한다.
# 풀지 않으면 \[NASDAQ: BKNG\] 나 \*\*\* 가 화면에 그대로 나온다.
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~])")

# 외부 링크. 스킴을 정규식에서 http/https 로 못박는다. 화이트리스트를 뒤에서
# 검사하는 대신 아예 매치가 안 되게 하면 javascript: 같은 것은 링크가 되지
# 않고 그냥 글자로 남는다. 이 함수는 html.escape 를 먼저 돌리므로 URL 안의
# 따옴표는 이미 &quot; 이고 속성 밖으로 새지 않는다.
_LINK = re.compile(r"\[([^\[\]]+)\]\((https?://[^\s)]+)\)")


def _inline(text: str, link: bool = True) -> str:
    out = _ESCAPED.sub(r"\1", html.escape(text))
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    if link:
        # 임베드(![[x]])를 먼저 걷어낸다. 옵시디언 전용 문법이라 여기서는 못
        # 그린다. 그냥 두면 '!' 만 남고 깨진 링크가 되어 있던 것을 사용자가
        # 발견했다. .base 는 마크다운도 아니라 링크로 만들면 404 다.
        out = re.sub(
            r"!\[\[([^\]|]+)\]\]",
            lambda m: f'<p class="empty">[{m.group(1)}] — 옵시디언에서 표로 보인다</p>',
            out,
        )
        # 위키링크를 먼저 처리한다. 그래야 [[x]] 가 외부 링크 패턴에 걸리지 않는다.
        # 별칭형([[경로|표시]])을 먼저 잡는다. 아래 패턴은 | 를 제외하므로
        # 별칭 링크가 매칭되지 않고 원문 그대로 남아 있던 것을 사용자가 발견했다.
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
    """vault 가 만들어내는 부분집합만 처리한다. 범용 마크다운 파서가 아니다."""
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
        # 코드 펜스. 안쪽은 마크다운으로 해석하지 않고 그대로 보존한다.
        # 계산식·다이어그램이 여기 들어가는데, 문단으로 흘리면 줄바꿈과
        # 공백 정렬이 전부 무너진다.
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
    # 닫히지 않은 펜스도 버리지 않는다. 내용이 사라지는 것이 최악이다.
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

# 웹뷰가 목록 페이지를 내주는 폴더. 상태 화면에는 올리지 않는다 - 메인은
# 작업 상태를 보는 곳이고, 여기에 볼거리를 섞으면 성격이 흐려진다.
_FOLDER_PAGES = {"concepts": "개념 정리", "library": "가져온 자료",
                 "records": "기록", "rest": "쉴 때 할 것",
                 "jobs": "채용 공고", "companies": "회사"}

# 미확정 항목. 노트마다 흩어져 있으면 결국 아무도 안 본다. 마크다운 체크박스를
# 그대로 쓰므로 옵시디언에서도 클릭으로 닫힌다. 열린 것만 모은다.
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
    """폴더 하나를 표로 세운다.

    베이스(.base) 는 옵시디언에서만 렌더된다. 웹뷰에 목록이 없으면 URL 을
    손으로 치는 수밖에 없고, 실제로 그래서 안 보였다.
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
    """vault 안의 마크다운만 돌려준다. 경로 탈출을 막는다."""
    # 이름을 먼저 좁힌다. 경로 구분자나 .. 가 들어오면 glob 패턴으로도, 경로
    # 조립으로도 위험하다. glob 은 절대 경로 패턴에서 예외까지 던진다.
    #
    # 중첩 경로(library/jobs/<공고>/<날짜>)를 허용하되 구분자만 풀지 않는다.
    # 세그먼트마다 같은 검사를 통과시키고 첫 세그먼트를 알려진 폴더로 제한한다.
    # 검사를 통째로 느슨하게 하면 탈출 경로가 다시 열린다.
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

    def log_message(self, *args) -> None:  # 접근 로그를 stderr 로 흘리지 않는다
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
            # 영문 원문 아래에 한국어 번역을 이어 붙인다. 번역을 원문 파일에
            # 섞으면 job-watch 의 변경 감지가 매번 '변경됨'을 낸다.
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
    """주기적으로 claude-mem 을 증분 임포트한다.

    ingest 는 events.ndjson 에 append 만 하고 vault 는 절대 건드리지 않는다.
    그래서 Obsidian 이 열려 있어도 안전하고 자주 돌려도 된다. vault 를 쓰는
    것은 compile 뿐이고 그것은 야간에만 돈다.
    """
    ingest = _load("ingest")
    db = Path.home() / ".claude-mem" / "claude-mem.db"
    while True:
        time.sleep(seconds)
        try:
            if db.exists():
                ingest.run(home, db)
        except Exception as exc:  # 갱신 실패가 서버를 죽이면 안 된다
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
