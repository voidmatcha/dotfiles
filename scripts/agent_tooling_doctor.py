#!/usr/bin/env python3
"""LLM 도구 계층의 결과 검사.

claude.sh / codex.sh / skills.sh 는 성공을 반환해도 반영되지 않을 수 있다.
하루에 같은 병을 넷 봤다.

  claude-mem       설치돼 있는데 Codex 훅이 매 호출마다 거부됨. 두 달간 유실
  local-skills     "최신"이라는데 캐시가 27일 묵고 스킬 두 개가 빠져 있었음
  ui-clone-skills  설치돼 있는데 캐시에 스킬 0개
  이 검사 자체      0파일끼리 비교해서 "일치"라고 보고

공통점은 성공을 보고하는데 효과가 없다는 것이다. 버전 비교는 대리 지표이므로,
여기서는 "그 도구가 원래 할 일을 하고 있나"를 본다.

사실만 낸다. 해석과 결정은 호출자(사람 또는 dotfiles-sync 스킬)의 몫이다.
출력은 `이름<TAB>상태<TAB>설명` 한 줄씩이며, doctor.sh 가 그대로 소비한다.

상태: ok / same(=ok) / info / stale / missing / local / error / unknown / skip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE_ROOT = Path.home() / ".claude/plugins/cache"
KNOWN_MARKETPLACES = Path.home() / ".claude/plugins/known_marketplaces.json"
INSTALLED_PLUGINS = Path.home() / ".claude/plugins/installed_plugins.json"
CLAUDE_MEM_DB = Path.home() / ".claude-mem/claude-mem.db"
LLMWIKI_PORT = 8391
CODEX_HOOKS = Path.home() / ".codex/hooks.json"

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", "node_modules"}
SKIP_NAMES = {".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

CAPTURE_WINDOW_DAYS = 7
MARKETPLACE_STALE_DAYS = 7


def repo_root() -> Path:
    """설치 심링크에서 저장소 위치를 역산한다. 경로를 추측하지 않는다."""
    env = os.environ.get("DOTFILES_DIR")
    if env:
        return Path(env)
    for link in (".zshrc", ".agent/AGENTS.md", ".claude/settings.json"):
        try:
            resolved = Path(os.readlink(Path.home() / link))
        except OSError:
            continue
        root = resolved.parent.parent
        if (root / "scripts").is_dir():
            return root
    return Path(__file__).resolve().parent.parent


def tree_digest(root: Path) -> tuple[str, int]:
    """디렉터리 내용 해시와 파일 수.

    os.walk(followlinks=True) 를 쓴다. Path.rglob 은 심링크 디렉터리로 내려가지
    않아, 심링크 팜으로 구성된 저장소에서 파일이 0개로 집계된다. 실측에서 소스가
    210파일인데 rglob 은 0을 돌려줬고, 0끼리 비교한 결과 비어 있는 캐시를
    "일치"로 보고했다.
    """
    if not root.is_dir():
        return "", 0
    entries: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in SKIP_NAMES or Path(name).suffix in SKIP_SUFFIXES:
                continue
            full = Path(dirpath) / name
            entries.append((str(full.relative_to(root)), full))
    digest = hashlib.sha256()
    count = 0
    for rel, full in sorted(entries):
        try:
            data = full.read_bytes()
        except OSError:
            continue
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(data + b"\0")
        count += 1
    return digest.hexdigest(), count


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


# --- 검사 ---------------------------------------------------------------


def check_session_capture(_root: Path) -> list[tuple[str, str, str]]:
    """두 하네스의 세션이 실제로 기록되고 있나. 이것이 결과 지표다."""
    if not CLAUDE_MEM_DB.is_file():
        return [("session-capture", "skip", "claude-mem db 없음")]
    try:
        con = sqlite3.connect(f"file:{CLAUDE_MEM_DB}?mode=ro", uri=True)
        con.execute("PRAGMA busy_timeout = 3000")
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=CAPTURE_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = dict(con.execute(
            "SELECT platform_source, COUNT(*) FROM sdk_sessions "
            "WHERE started_at >= ? GROUP BY 1", (cutoff,)))
        con.close()
    except sqlite3.Error as exc:
        return [("session-capture", "error", str(exc))]
    out = []
    for harness in ("claude", "codex"):
        count = rows.get(harness, 0)
        state = "ok" if count else "missing"
        out.append(("session-capture", state,
                    f"{harness}: {count} sessions in {CAPTURE_WINDOW_DAYS}d"))
    return out


def check_codex_hooks(_root: Path) -> list[tuple[str, str, str]]:
    """claude-mem 이 Codex 훅에 등록돼 있나. 없으면 Codex 기록이 통째로 빈다."""
    data = _load_json(CODEX_HOOKS)
    if data is None:
        return [("codex-hooks", "skip", "hooks.json 없음 또는 파싱 불가")]
    present = sorted(
        event for event, blocks in data.get("hooks", {}).items()
        if any("claude-mem" in hook.get("command", "")
               for block in blocks for hook in block.get("hooks", []))
    )
    state = "ok" if present else "missing"
    return [("codex-hooks", state, f"claude-mem on: {','.join(present) or 'nothing'}")]


def check_marketplace_age(_root: Path) -> list[tuple[str, str, str]]:
    """마켓플레이스 캐시가 묵으면 update 가 최신을 못 본다."""
    if not KNOWN_MARKETPLACES.is_file():
        return [("marketplace-age", "skip", "known_marketplaces.json 없음")]
    age = (datetime.now().timestamp() - KNOWN_MARKETPLACES.stat().st_mtime) / 86400
    state = "ok" if age <= MARKETPLACE_STALE_DAYS else "stale"
    return [("marketplace-age", state, f"{int(age)} days since last refresh")]


LAUNCH_AGENTS = Path.home() / "Library/LaunchAgents"
# 리포가 소유하는 작업. plist 는 심링크가 아니라 복사본으로 설치되므로
# (로그인 시점 launchd 가 심링크를 읽는다는 보장이 없다) 사본이 낡을 수 있다.
REPO_LAUNCH_JOBS = {
    "com.yongjae.llmwiki": "configs/llmwiki",
    "com.yongjae.llmwiki-web": "configs/llmwiki",
    "com.yongjae.dotfiles-doctor": "configs/launchd",
}


def check_launchd_jobs(root: Path) -> list[tuple[str, str, str]]:
    """예약 작업이 설치돼 있고, 로드돼 있고, 리포와 같은가.

    세 가지가 각각 다른 사실이다. 파일만 있고 로드가 안 됐거나, 로드는 됐는데
    내용이 낡았거나 - 어느 쪽이든 "설치했다"는 기억만으로는 알 수 없다.
    """
    if not LAUNCH_AGENTS.is_dir():
        return [("launchd", "skip", "LaunchAgents 디렉터리 없음")]

    loaded: set[str] = set()
    try:
        proc = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
        loaded = {ln.split("\t")[-1].strip() for ln in proc.stdout.splitlines()[1:] if ln.strip()}
    except (OSError, subprocess.SubprocessError):
        return [("launchd", "unknown", "launchctl 조회 실패")]

    out = []
    for label, subdir in sorted(REPO_LAUNCH_JOBS.items()):
        src = root / subdir / f"{label}.plist"
        dst = LAUNCH_AGENTS / f"{label}.plist"
        if not src.is_file():
            out.append(("launchd", "unknown", f"{label} 리포에 plist 없음"))
        elif not dst.exists():
            out.append(("launchd", "missing", f"{label} 설치되지 않았다 — install.sh 를 돌려라"))
        elif dst.is_symlink():
            out.append(("launchd", "stale",
                        f"{label} 이 심링크다 — 로그인 시점 launchd 가 따라간다는 보장이 없다"))
        elif src.read_bytes() != dst.read_bytes():
            out.append(("launchd", "stale",
                        f"{label} 설치본이 리포와 다르다 — install.sh 를 다시 돌려야 반영된다"))
        elif label not in loaded:
            out.append(("launchd", "missing", f"{label} 파일은 있는데 로드되지 않았다"))
        else:
            out.append(("launchd", "ok", f"{label} 설치·로드·동기 상태"))
    return out


LLMWIKI_STATE = Path.home() / ".local/share/llmwiki"
LLMWIKI_ERRLOG = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) \
    / "llmwiki" / "hook-errors.log"
LLMWIKI_PLIST = Path.home() / "Library/LaunchAgents/com.yongjae.llmwiki.plist"
CLAUDE_MEM_DB = Path.home() / ".claude-mem/claude-mem.db"


def _llmwiki_host() -> str:
    """llmwiki 가 워터마크 키에 쓰는 것과 같은 호스트 이름.

    config.host() 를 그대로 옮겼다. doctor 는 llmwiki 를 import 하지 않으므로
    복제가 불가피한데, 어긋나면 이 검사가 항상 '적재 정지' 를 외치게 된다.
    """
    raw = os.environ.get("LLMWIKI_HOST") or socket.gethostname().split(".")[0]
    return re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower() or "unknown"


def _llmwiki_vault(state: Path) -> Path | None:
    """config.toml 의 vault 키. 없으면 기본값. doctor 는 llmwiki 를 import
    하지 않으므로 최소한으로 다시 읽는다."""
    # 상대경로는 config 가 있는 디렉터리를 기준으로 푼다. cwd 기준으로 두면
    # doctor 와 compile 이 서로 다른 절대경로를 얻어 거짓 교체 경보가 난다.
    def anchored(raw: str) -> Path:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else state / p

    raw = os.environ.get("LLMWIKI_VAULT")
    if raw:
        return anchored(raw)
    cfg = state / "config.toml"
    if cfg.is_file():
        for line in cfg.read_text(errors="replace").splitlines():
            m = re.match(r'\s*vault\s*=\s*"([^"]*)"', line)
            if m and m.group(1):
                return anchored(m.group(1))
    return Path.home() / "Documents/llmwiki"


def _binding_task_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.is_file():
        return ids
    for line in path.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("task_id"):
            ids.add(str(row["task_id"]))
    return ids


def check_llmwiki_capture(_root: Path) -> list[tuple[str, str, str]]:
    """llmwiki 가 실제로 기록하고 있나. 등록 여부가 아니라 결과를 본다.

    훅은 fail-open 이라 깨져도 세션을 막지 않는다. 그 조용함이 위험해서
    실패를 로그로 남기고 여기서 읽는다. 야간 작업도 마찬가지로 "로드됨"이
    아니라 "최근에 돌았나"를 묻는다 - claude-mem 은 버전이 최신인 채로 두 달
    아무것도 기록하지 않았다.
    """
    out: list[tuple[str, str, str]] = []
    state = LLMWIKI_STATE
    if not state.is_dir():
        return [("llmwiki-capture", "skip", "llmwiki 상태 디렉터리 없음")]

    errlog = LLMWIKI_ERRLOG
    if errlog.is_file():
        # 로그는 append 전용이고 아무것도 정리하지 않는다. 창이 없으면 한 번의
        # 일시적 실패가 영원히 stale 로 남아 매주 알림을 울리고, 사람은 그
        # 알림을 무시하게 된다. 무시하는 습관이 두 달짜리 사고를 만들었다.
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=CAPTURE_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # 앞 필드가 타임스탬프인 줄만 센다. 부분 기록으로 앞이 잘린 줄은
        # ASCII 에서 글자가 숫자보다 뒤라 어떤 cutoff 보다도 크게 비교되어
        # 영원히 '최근 실패' 로 남는다. 매주 울리는 경보를 무시하게 되면
        # 거짓 정상과 결과가 같다.
        recent = []
        for ln in errlog.read_text(errors="replace").splitlines():
            head = ln.split("\t", 1)[0]
            if re.match(r"\d{4}-\d{2}-\d{2}T", head) and head >= cutoff:
                recent.append(ln)
        if recent:
            out.append(("llmwiki-capture", "stale",
                        f"훅 실패 {len(recent)}건 (최근 {CAPTURE_WINDOW_DAYS}일) "
                        f"— 마지막: {recent[-1][:110]}"))

    # 워터마크가 claude-mem 을 따라잡고 있나. 벌어지면 적재가 멈춘 것이다.
    # 이 머신의 키만 본다. max() 를 쓰면 동기화된 다른 머신의 값이나
    # hostname 변경으로 남은 옛 키가 우리 정지를 가린다 - 남의 최신 값 때문에
    # 한 건도 적재하지 않은 채 "적재 최신" 이 나온다.
    key = f"claude-mem:{_llmwiki_host()}"
    try:
        marks = json.loads((state / "state.json").read_text())["watermark"]
        watermark = int(marks.get(key, 0))
    except Exception as exc:
        out.append(("llmwiki-capture", "error", f"state.json 읽기 실패: {exc}"))
        watermark = None

    db = CLAUDE_MEM_DB
    if watermark is not None and db.is_file():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            newest = con.execute("SELECT COALESCE(MAX(id), 0) FROM session_summaries").fetchone()[0]
            con.close()
        except sqlite3.Error as exc:
            out.append(("llmwiki-capture", "unknown", f"claude-mem 조회 실패: {exc}"))
        else:
            behind = newest - watermark
            if behind < 0:
                # 워터마크가 db 를 앞선다. claude-mem 재설치나 db 복원으로
                # id 가 1부터 다시 시작하면 이렇게 되고, ingest 의
                # WHERE s.id > watermark 는 그 뒤로 영원히 아무것도 못 맞춘다.
                # 음수를 그냥 두면 임계값을 못 넘어 '적재 최신' 이 되고,
                # session-capture 는 새 db 가 잘 기록되니 초록이다.
                out.append(("llmwiki-capture", "stale",
                            f"워터마크({watermark})가 db 최신 id({newest})보다 앞선다 — "
                            f"db 가 교체됐다. 적재가 영구히 멈춘 상태이므로 "
                            f"state.json 의 워터마크를 리셋해야 한다"))
                behind = None
            # 고정 임계값만 쓰면 새 머신에서 정지가 가려진다. db 가 200건
            # 미만일 때는 한 건도 적재하지 않아도 임계값을 못 넘어 정상으로
            # 읽히고, db 가 커질 때까지 계속 조용하다. 절대값과 비율 중
            # 엄격한 쪽을 쓴다.
            limit = min(200, max(10, newest // 4))
            if behind is None:
                pass
            elif behind > limit:
                out.append(("llmwiki-capture", "stale",
                            f"적재가 {behind}세션 밀렸다 (워터마크 {watermark} / 최신 {newest})"))
            else:
                out.append(("llmwiki-capture", "ok",
                            f"적재 최신 (뒤처짐 {behind}세션)"))

    # 설정이 가리키는 볼트와 실제로 쓰이는 볼트가 같나. env 로만 바꾸던
    # 시절에는 CLI 가 한쪽, 훅과 launchd 가 다른 쪽에 쓰면서 볼트가 조용히
    # 둘로 갈라졌다. 이제 config.toml 이 정답이지만, 셸에 남은 옛 환경변수가
    # 여전히 CLI 만 다른 곳으로 보낼 수 있다.
    env_vault = os.environ.get("LLMWIKI_VAULT")
    if env_vault:
        out.append(("llmwiki-capture", "stale",
                    f"LLMWIKI_VAULT 가 셸에 설정돼 있다 ({env_vault}) — 훅과 launchd 는 "
                    "이 값을 보지 못한다. config.toml 의 vault 키를 쓰고 환경변수를 지워라"))

    # 볼트에만 존재하는 것들. events 에서 되살아나지 않으므로, 볼트를
    # 잃으면 여기 있는 것도 함께 사라진다. 실측으로 확인했다 - 경로를
    # 바꾸고 compile 하니 GEN 밖의 글과 태스크 페이지가 조용히 없어졌다.
    vault = _llmwiki_vault(state)

    # 교체 경고는 compile 이 stderr 로 한 번 내고 끝이다. 야간 작업이 처음
    # 알아챘다면 그 한 줄은 /tmp/llmwiki.err 에 들어가고 이후 실행은 조용하다.
    # state 가 기억하는 마지막 컴파일 볼트와 설정이 가리키는 볼트를 여기서
    # 대보면 주간 검사가 계속 보여준다.
    try:
        last = str(json.loads((state / "state.json").read_text()).get("vault", "") or "")
    except Exception:
        last = ""
    if last and vault and last != str(vault.resolve()):
        out.append(("llmwiki-capture", "stale",
                    f"마지막으로 컴파일한 볼트는 {last} 인데 설정은 {vault} 를 가리킨다 — "
                    f"직접 쓴 글과 tasks/ 는 옛 볼트에만 있다"))

    # 교체된 옛 볼트에 내용이 남아 있나. 승인 절차 대신 이걸 묻는다 -
    # 지우거나 합치면 저절로 조용해지고, 남아 있는 동안만 알린다.
    try:
        stranded = json.loads((state / "state.json").read_text()).get("vaults_previous", []) or []
    except Exception:
        stranded = []
    current = str(vault.resolve()) if vault else ""
    for previous in [v for v in stranded if v and v != current]:
        old_vault = Path(previous)
        # .md 만 보면 bases/*.base 나 사람이 넣은 첨부만 남은 볼트를
        # "비었다" 고 읽는다. 표식 파일과 디렉터리를 뺀 나머지가 하나라도
        # 있으면 잃을 것이 있다고 본다.
        # 현재 볼트가 옛 볼트 안에 있을 수 있다 (예: ~/x/vault → ~/x/vault/wiki).
        # 그러면 옛 경로를 훑을 때 살아있는 볼트의 파일이 잡히고, "옮기거나
        # 지워라" 가 살아있는 볼트를 지우라는 말이 된다 - 해소할 수 없는
        # 경보다. 현재 볼트 아래는 세지 않는다.
        here = Path(current) if current else None
        leftovers = [
            f for f in old_vault.rglob("*")
            if f.is_file() and f.name != ".llmwiki-vault"
            and not (here and (f == here or here in f.parents))
        ] if old_vault.is_dir() else []
        if leftovers:
            out.append(("llmwiki-capture", "stale",
                        f"옛 볼트에 파일 {len(leftovers)}개가 남아 있다: {previous} — "
                        f"직접 쓴 글과 tasks/ 는 거기에만 있다. "
                        f"옮기거나 지우면 이 경고는 사라진다"))

    if vault and vault.is_dir():
        binds = _binding_task_ids(state / "bindings.ndjson")
        # 태스크 페이지는 제목이 있으면 T-0001-제목.md, 없으면 T-0001.md 다
        # (tasks.py:59). '-' 로 잘라 앞 두 조각을 붙이면 후자가 'T-0001.md' 가
        # 되어 바인딩과 영원히 어긋나고, 멀쩡한 상태를 고아로 신고한다.
        have = {m.group(1) for m in
                (re.match(r"(T-\d+)", p.name) for p in (vault / "tasks").glob("T-*.md"))
                if m} if (vault / "tasks").is_dir() else set()
        orphans = sorted(binds - have)
        if orphans:
            out.append(("llmwiki-capture", "stale",
                        f"바인딩이 가리키는 태스크 페이지가 없다: {', '.join(orphans[:5])} — "
                        f"볼트가 교체됐거나 페이지가 지워졌다"))
        stamp = vault / ".llmwiki-vault"
        if not stamp.exists():
            out.append(("llmwiki-capture", "unknown",
                        f"볼트에 정체성 표식이 없다 ({vault}) — compile 한 번이면 생긴다"))
        elif stamp.read_text(errors="replace").strip() != str(vault.resolve()):
            out.append(("llmwiki-capture", "stale",
                        f"볼트가 다른 경로에서 옮겨졌다 — 직접 쓴 글과 tasks/ 를 확인하라"))

    # 뷰어가 실제로 응답하나. 프로세스가 살아 있어도 포트가 죽어 있을 수 있고,
    # tmux 안에서 돌던 시절에는 창이 닫히면 조용히 사라졌다.
    web_plist = LLMWIKI_PLIST.with_name("com.yongjae.llmwiki-web.plist")
    if web_plist.exists():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{LLMWIKI_PORT}/", timeout=3) as r:
                code = r.status
        except Exception as exc:
            out.append(("llmwiki-capture", "stale",
                        f"뷰어가 :{LLMWIKI_PORT} 에서 응답하지 않는다: {exc}"))
        else:
            out.append(("llmwiki-capture", "ok", f"뷰어 응답 {code} (:{LLMWIKI_PORT})"))

    # 야간 작업이 최근에 돌았나.
    plist = LLMWIKI_PLIST
    snaps = sorted((state / "snapshots").glob("*")) if (state / "snapshots").is_dir() else []
    if not plist.exists():
        out.append(("llmwiki-capture", "missing",
                    "야간 작업이 설치되지 않았다 — 적재/컴파일이 자동으로 돌지 않는다"))
    elif not snaps:
        out.append(("llmwiki-capture", "stale", "스냅샷이 하나도 없다 — 야간 작업이 돈 적 없다"))
    else:
        age = (time.time() - snaps[-1].stat().st_mtime) / 86400
        state_ = "ok" if age < 3 else "stale"
        out.append(("llmwiki-capture", state_,
                    f"마지막 스냅샷 {age:.1f}일 전 ({snaps[-1].name})"))
    return out


def check_orphaned_cache(_root: Path) -> list[tuple[str, str, str]]:
    """Claude Code 는 .orphaned_at 을 찍지만 지우지 않는다.

    `claude plugin prune` 은 의존성 플러그인만 보고 버전 캐시는 건드리지 않는다.
    편집마다 버전이 오르는 로컬 플러그인에서 계속 쌓인다. 보고만 한다 - 삭제는
    되돌릴 수 없고 실행 중인 세션이 그 경로를 읽고 있을 수 있다.
    """
    if not CACHE_ROOT.is_dir():
        return [("orphaned-cache", "skip", "캐시 루트 없음")]

    out: list[tuple[str, str, str]] = []

    # 중단된 설치가 남긴 임시 트리. directory 소스를 설치하면 Claude Code 가
    # 저장소 전체를 temp_local_* 로 복사하는데, 그 사이에 프로세스가 죽으면
    # 그대로 남는다. 실측에서 개발 저장소 하나가 49GB 를 남겼고 디스크 여유가
    # 3.3GB 까지 떨어졌다. 아무도 참조하지 않으므로 지워도 안전하다.
    temps = [d for d in CACHE_ROOT.glob("temp_local_*") if d.is_dir()]
    if temps:
        size = sum(f.stat().st_size for d in temps for f in d.rglob("*") if f.is_file())
        out.append(("orphaned-cache", "stale",
                    f"중단된 설치 잔해 {len(temps)}개 {size // 1024 // 1024}MB — "
                    f"참조되지 않는다. rm -rf {CACHE_ROOT}/temp_local_*"))

    # 버전 캐시는 marketplace/plugin/version 세 단계다. 그보다 얕거나 깊은
    # 경로의 .orphaned_at 은 다른 도구의 마커이므로 세지 않는다.
    total = count = 0
    for marker in CACHE_ROOT.glob("*/*/*/.orphaned_at"):
        version_dir = marker.parent
        if version_dir.name.startswith("temp_local_") or \
                version_dir.parent.parent.name.startswith("temp_local_"):
            continue
        count += 1
        total += sum(f.stat().st_size for f in version_dir.rglob("*") if f.is_file())
    if count:
        out.append(("orphaned-cache", "info",
                    f"고아 버전 {count}개 {total // 1024 // 1024}MB — 자동 정리되지 않는다"))
    return out or [("orphaned-cache", "ok", "고아 캐시 없음")]


def _plugin_version(root: Path) -> str | None:
    manifest = _load_json(root / ".claude-plugin" / "plugin.json")
    return str(manifest.get("version")) if manifest and manifest.get("version") else None


def check_duplicate_checkouts(_root: Path) -> list[tuple[str, str, str]]:
    """같은 저장소가 두 곳에 독립적으로 체크아웃돼 있나.

    claude.sh 는 ui-clone-skills 를 ~/.local/share 에 클론하지만 개발은
    ~/Documents 에서 하기 쉽다. 이 머신은 전자가 후자를 가리키는 심링크라
    하나지만, 새 머신에서는 각각 독립된 클론이 될 수 있다. 그러면 한쪽에서
    고친 것이 다른 쪽에 가지 않고, 도구는 조용히 옛 쪽을 읽는다.

    심링크로 이어져 있으면 같은 실체이므로 보고하지 않는다.
    """
    # 개발 체크아웃 경로는 이름이 바뀐다 - ui-skills 는 실제로 ui-clone-skills
    # 로 바뀌었다. 한 이름만 박아두면 그 뒤로는 아무것도 비교하지 않으면서
    # 조용히 통과한다. 후보를 훑어 실재하는 것을 쓴다.
    checkouts = [Path.home() / "Documents/ui-clone-skills",
                 Path.home() / "Documents/ui-skills"]
    dev = next((p for p in checkouts if p.is_dir()), None)
    if dev is None:
        # 아무 줄도 내지 않으면 "검사했고 문제없음" 과 구분되지 않는다.
        # 검사하지 않았다는 사실 자체를 말한다.
        return [("duplicate-checkout", "skip",
                 "개발 체크아웃을 찾지 못했다: "
                 + ", ".join(str(p) for p in checkouts))]
    out = []

    # 플러그인을 실제로 먹이는 경로를 본다. 이름을 박아두면 마켓플레이스가
    # 제3의 경로를 가리킬 때 서로 일치하는 엉뚱한 쌍만 보며 ok 를 낸다.
    # 실측: 소스는 ~/.local/share/ui-clone-skills-claude-src 라는 분리된
    # 복사본(git 도 심링크도 아님)이고 plugin.json 이 0.7.25 인데 개발
    # 체크아웃은 0.7.26 이었다. 이후 커밋은 플러그인에 닿지 않는다.
    known = _load_json(KNOWN_MARKETPLACES) or {}
    for market, entry in sorted(known.items()):
        src = (entry.get("source") or {})
        if src.get("source") != "directory" or not src.get("path"):
            continue
        served = Path(src["path"])
        if not served.is_dir() or served.resolve() == dev.resolve():
            continue
        sv = _plugin_version(served)
        dv = _plugin_version(dev)
        if sv is None or dv is None:
            continue
        if sv != dv:
            out.append(("duplicate-checkout", "stale",
                        f"{market} 마켓플레이스가 {served} 를 서빙한다 (version {sv}) "
                        f"— 개발 체크아웃 {dev} 는 {dv} 다. 이후 커밋은 플러그인에 닿지 않는다"))
        else:
            out.append(("duplicate-checkout", "ok",
                        f"{market} 소스와 개발 체크아웃 version 일치 ({sv})"))

    pairs = [(Path.home() / ".local/share/ui-clone-skills", dev)]
    for a, b in pairs:
        if not (a.is_dir() and b.is_dir()):
            continue
        try:
            same = a.resolve() == b.resolve()
        except OSError:
            continue
        label = f"{a.name}: {a.parent.name} vs {b.parent.name}"
        if same:
            out.append(("duplicate-checkout", "ok", f"{label} 같은 실체"))
        else:
            out.append(("duplicate-checkout", "stale",
                        f"{label} 독립된 체크아웃 둘 — 한쪽 편집이 다른 쪽에 가지 않는다"))
    return out


def check_plugin_versions(_root: Path) -> list[tuple[str, str, str]]:
    """캐시에 여러 버전이 남아 있으면 구버전이 아직 참조될 수 있다."""
    installed = _load_json(INSTALLED_PLUGINS)
    if installed is None:
        return [("plugin-drift", "skip", "installed_plugins.json 없음")]
    out = []
    for key in sorted(installed.get("plugins", {})):
        if "@" not in key:
            continue
        name, owner = key.split("@", 1)
        base = CACHE_ROOT / owner / name
        if not base.is_dir():
            continue
        versions = sorted(
            (tuple(int(x) for x in d.name.split(".")), d.name)
            for d in base.iterdir()
            if d.is_dir() and not (d / ".orphaned_at").exists()
            and re.fullmatch(r"[0-9]+(\.[0-9]+)*", d.name)
        )
        if not versions:
            continue
        newest = versions[-1][1]
        extra = [v for _, v in versions[:-1]]
        state = "ok" if not extra else "info"
        detail = f"{key} newest={newest}"
        if extra:
            detail += f" also-live={','.join(extra)}"
        out.append(("plugin-drift", state, detail))
    return out


_BUILD_RESIDUE = {".venv", "venv", "node_modules", "__pycache__",
                  ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return sorted(path.iterdir())
    except OSError:
        return []


def _count_files(path: Path) -> int:
    n = 0
    for _, _, files in os.walk(path, followlinks=False):
        n += len(files)
        if n > 0:
            return n
    return n


def _tree_kib(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total // 1024


def check_local_plugin_cache(_root: Path) -> list[tuple[str, str, str]]:
    """directory 소스 플러그인이 실제로 배달됐고, 캐시가 소스와 같나.

    `claude plugin install` 은 선언된 소스 경로를 캐시로 복사하고 런타임은
    그 사본만 읽는다. 실측으로 확인한 두 가지:

    - 최상위 심링크는 따라가지 않는다. 심링크 프로젝션을 소스로 등록하면
      설치는 성공을 보고하면서 캐시에 아무것도 만들지 않는다.
    - `.gitignore` 는 적용되지 않는다. 소스에 있는 것은 전부 복사된다.

    그래서 "설치됨"과 "배달됨"은 다른 사실이고, 이 검사는 후자를 본다.
    `claude plugin details` 는 마켓플레이스 매니페스트를 읽으므로 캐시가
    비어 있어도 스킬 목록을 정상 출력한다 — 판정 근거로 쓸 수 없다.
    """
    known = _load_json(KNOWN_MARKETPLACES)
    if known is None:
        return [("local-plugin-cache", "skip", "known_marketplaces.json 없음")]

    out = []
    for market, entry in sorted(known.items()):
        source = entry.get("source") or {}
        if source.get("source") != "directory" or not source.get("path"):
            continue
        repo = Path(source["path"])
        if not repo.is_dir():
            out.append(("local-plugin-cache", "missing", f"{market} 소스 경로 없음: {repo}"))
            continue

        # marketplace.json 의 source 가 판정 방식을 가른다. 하위 경로를 가리키면
        # Claude Code 가 그 부분을 캐시로 복사하므로 캐시가 묵을 수 있다. './' 로
        # 저장소 루트를 가리키면 소스를 직접 참조하고 캐시는 비어 있는 것이 정상이다.
        # 실측: dotfiles-local 은 './plugins/local-skills' 라 캐시에 19개,
        # voidmatcha 는 './' 라 캐시 0개인데 plugin details 는 스킬 4개를 본다.
        mkt = _load_json(repo / ".claude-plugin" / "marketplace.json") or {}
        sources = {e.get("name"): (e.get("source") or "") for e in mkt.get("plugins", [])}
        installed = (_load_json(INSTALLED_PLUGINS) or {}).get("plugins", {})

        plugin_dirs = []
        if (repo / ".claude-plugin" / "plugin.json").is_file():
            plugin_dirs.append(repo)
        if (repo / "plugins").is_dir():
            plugin_dirs += [c for c in sorted((repo / "plugins").glob("*"))
                            if (c / ".claude-plugin" / "plugin.json").is_file()]

        for plugin_dir in plugin_dirs:
            manifest = _load_json(plugin_dir / ".claude-plugin" / "plugin.json") or {}
            # 이름은 매니페스트가 선언한다. 디렉터리명과 다를 수 있고,
            # 실제로 ui-skills/ 안의 플러그인 이름은 ui-clone-skills 다.
            name = manifest.get("name") or plugin_dir.name
            version = manifest.get("version", "")
            declared = str(sources.get(name, ""))
            src = repo if declared in ("", "./", ".") else repo / declared.lstrip("./")

            entries = installed.get(f"{name}@{market}") or []
            if not entries:
                out.append(("local-plugin-cache", "info",
                            f"{market}/{name} {version} 마켓플레이스에만 있고 설치되지 않았다"))
                continue
            cache = Path(entries[0].get("installPath") or (CACHE_ROOT / market / name / version))

            cache_files = _count_files(cache)
            if cache_files == 0:
                why = ""
                if any(c.is_symlink() for c in _safe_iterdir(src)):
                    why = " — 소스 최상위가 심링크다. 설치기는 심링크를 따라가지 않는다"
                out.append(("local-plugin-cache", "stale",
                            f"{market}/{name} {version} 설치됐다는데 캐시에 파일이 없다 "
                            f"({cache}){why}"))
                continue

            residue = [d.name for d in _safe_iterdir(cache) if d.name in _BUILD_RESIDUE]
            if residue:
                kib = _tree_kib(cache)
                out.append(("local-plugin-cache", "stale",
                            f"{market}/{name} {version} 캐시에 빌드 잔여물이 실렸다: "
                            f"{','.join(sorted(residue))} (전체 {kib // 1024}MB) — "
                            f"소스에서 제외해야 한다"))
                continue

            src_digest, src_n = tree_digest(src / "skills")
            cache_digest, cache_n = tree_digest(cache / "skills")
            if src_n == 0 or cache_n == 0:
                state = "unknown"
                detail = (f"{market}/{name} {version} skills/ 비교 불가 "
                          f"(소스 {src_n} / 캐시 {cache_n})")
            elif src_digest == cache_digest:
                state, detail = "same", f"{market}/{name} {version} 캐시가 소스와 일치"
            else:
                state = "stale"
                detail = (f"{market}/{name} {version} 캐시가 소스와 다름 "
                          f"(소스 {src_n}파일 / 캐시 {cache_n}파일) — 버전을 올려야 갱신된다")
            out.append(("local-plugin-cache", state, detail))
    return out or [("local-plugin-cache", "skip", "directory 소스 마켓플레이스 없음")]


def parse_upstream_skills(skills_sh: Path) -> list[dict]:
    """설치 대상과 핀된 URL 을 skills.sh 에서 직접 읽는다.

    목록을 복제하면 두 곳이 갈라진다. skills.sh 가 유일한 선언이다.
    """
    text = skills_sh.read_text(encoding="utf-8")
    refs = dict(re.findall(r'^([A-Z_]+)_REF="\$\{[A-Z_]+:-([0-9a-f]{40})\}"', text, re.M))
    urls = {}
    for key, url in re.findall(r'^([A-Z_]+)_SKILL_URL="([^"]+)"', text, re.M):
        for var, sha in refs.items():
            url = url.replace(f"${{{var}_REF}}", sha)
        urls[key] = url

    entries = []
    for tool, dest_expr, name, url_var in re.findall(
        r'install_upstream_skill_from_url\s+"(\w+)"\s+"([^"]+)"\s+"([^"]+)"\s+"\$(\w+)"', text
    ):
        dest = dest_expr.replace("$HOME", str(Path.home()))
        dest = dest.replace("$CODEX_CONFIG_DIR", str(Path.home() / ".codex"))
        entries.append({
            "tool": tool, "skill": name,
            "path": Path(f"{dest}/{name}/SKILL.md"),
            "url": urls.get(url_var.removesuffix("_SKILL_URL"), ""),
        })
    return entries


def check_upstream_skills(root: Path, offline: bool = False) -> list[tuple[str, str, str]]:
    """핀된 외부 스킬이 로컬에서 수정됐나.

    skills.sh 는 이제 덮어쓰기 전에 백업하지만, 백업이 생긴다는 것 자체가
    "업스트림에 반영할지 결정하라"는 신호다.
    """
    skills_sh = root / "scripts" / "skills.sh"
    if not skills_sh.is_file():
        return [("upstream-skill", "skip", "skills.sh 없음")]

    cache: dict[str, str] = {}
    out = []
    for entry in parse_upstream_skills(skills_sh):
        label = f"{entry['tool']}/{entry['skill']}"
        if not entry["path"].is_file():
            out.append(("upstream-skill", "missing", f"{label}: 설치되지 않음"))
            continue
        if offline or not entry["url"]:
            out.append(("upstream-skill", "unknown", f"{label}: 오프라인"))
            continue
        if entry["url"] not in cache:
            try:
                with urllib.request.urlopen(entry["url"], timeout=20) as fh:
                    cache[entry["url"]] = hashlib.sha256(fh.read()).hexdigest()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                cache[entry["url"]] = f"error:{exc}"
        remote = cache[entry["url"]]
        if remote.startswith("error:"):
            out.append(("upstream-skill", "unknown", f"{label}: {remote[6:]}"))
        elif hashlib.sha256(entry["path"].read_bytes()).hexdigest() == remote:
            out.append(("upstream-skill", "same", f"{label}: 핀과 동일"))
        else:
            out.append(("upstream-skill", "local",
                        f"{label}: 로컬에서 수정됨 — skills.sh 실행 시 덮어써진다"))
    return out


def check_skill_pins(root: Path) -> list[tuple[str, str, str]]:
    """핀은 안전하지만 영원히 두면 그것도 드리프트다."""
    skills_sh = root / "scripts" / "skills.sh"
    if not skills_sh.is_file():
        return []
    text = skills_sh.read_text(encoding="utf-8")
    return [("skill-pin", "info", f"{name} pinned at {sha[:7]}")
            for name, sha in re.findall(
                r'^([A-Z_]+)_REF="\$\{[A-Z_]+:-([0-9a-f]{40})\}"', text, re.M)]


CHECKS = {
    "session-capture": check_session_capture,
    "codex-hooks": check_codex_hooks,
    "local-plugin-cache": check_local_plugin_cache,
    "upstream-skill": check_upstream_skills,
    "plugin-drift": check_plugin_versions,
    "marketplace-age": check_marketplace_age,
    "launchd": check_launchd_jobs,
    "llmwiki-capture": check_llmwiki_capture,
    "orphaned-cache": check_orphaned_cache,
    "duplicate-checkout": check_duplicate_checkouts,
    "skill-pin": check_skill_pins,
}

BAD_STATES = {"stale", "missing", "local", "error"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--offline", action="store_true", help="네트워크를 쓰지 않는다")
    ap.add_argument("--only", action="append", choices=sorted(CHECKS), default=None)
    args = ap.parse_args()

    root = repo_root()
    results: list[tuple[str, str, str]] = []
    for name, fn in CHECKS.items():
        if args.only and name not in args.only:
            continue
        try:
            if fn is check_upstream_skills:
                results.extend(fn(root, offline=args.offline))
            else:
                results.extend(fn(root))
        except Exception as exc:  # 검사 하나가 죽어도 나머지는 낸다
            results.append((name, "error", f"검사 실패: {exc}"))

    if args.format == "json":
        print(json.dumps([{"check": c, "state": s, "detail": d} for c, s, d in results],
                         ensure_ascii=False, indent=2))
    else:
        for check, state, detail in results:
            print(f"{check}\t{state}\t{detail}")

    return 1 if any(s in BAD_STATES for _, s, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
