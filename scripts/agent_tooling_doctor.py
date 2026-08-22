#!/usr/bin/env python3
"""Outcome checks for the LLM tooling layer.

claude.sh / codex.sh / skills.sh can return success without the change taking
effect. Four cases of the same illness turned up in a single day.

  claude-mem       installed, but the Codex hook was rejected on every call.
                   Two months lost
  local-skills     reported "up to date" while the cache was 27 days old and
                   two skills were missing
  ui-clone-skills  installed, but the cache held 0 skills
  this check itself compared 0 files against 0 and reported "match"

What they share is reporting success with no effect. A version comparison is a
proxy metric, so what is checked here is "is that tool doing the job it exists
to do".

Facts only. Interpretation and decisions belong to the caller (a human or the
dotfiles-sync skill). Output is one `name<TAB>state<TAB>detail` line per row,
consumed as-is by doctor.sh.

States: ok / same(=ok) / info / stale / missing / local / error / unknown / skip
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
    """Derive the repo location back from the install symlinks. Never guess."""
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
    """Hash of the directory contents, plus the file count.

    Uses os.walk(followlinks=True). Path.rglob does not descend into symlinked
    directories, so a repo built as a symlink farm counts as 0 files. Measured:
    the source had 210 files and rglob returned 0, and comparing 0 against 0
    reported an empty cache as a "match".
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


# --- Checks -------------------------------------------------------------


def check_session_capture(_root: Path) -> list[tuple[str, str, str]]:
    """Are both harnesses' sessions actually recorded? This is the outcome."""
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
    """Is claude-mem registered in the Codex hooks? Without it Codex records nothing."""
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
    """A stale marketplace cache means update cannot see what is newest."""
    if not KNOWN_MARKETPLACES.is_file():
        return [("marketplace-age", "skip", "known_marketplaces.json 없음")]
    age = (datetime.now().timestamp() - KNOWN_MARKETPLACES.stat().st_mtime) / 86400
    state = "ok" if age <= MARKETPLACE_STALE_DAYS else "stale"
    return [("marketplace-age", state, f"{int(age)} days since last refresh")]


LAUNCH_AGENTS = Path.home() / "Library/LaunchAgents"
# Jobs owned by the repo. plists are installed as copies rather than symlinks
# (nothing guarantees launchd reads a symlink at login), so a copy can go stale.
REPO_LAUNCH_JOBS = {
    "com.yongjae.llmwiki": "configs/llmwiki",
    "com.yongjae.llmwiki-web": "configs/llmwiki",
    "com.yongjae.dotfiles-doctor": "configs/launchd",
}



# launchd does not expand variables in a plist, so a job that writes under the
# user's home is rendered at install time rather than copied. Comparing the
# installed file against the unrendered source reports every such job stale
# forever, which is how a real staleness check stops being read.
def _rendered(src: Path) -> bytes:
    return src.read_bytes().replace(b"__HOME__", str(Path.home()).encode())

def check_launchd_jobs(root: Path) -> list[tuple[str, str, str]]:
    """Is the scheduled job installed, loaded, and identical to the repo?

    Those are three separate facts. The file can be there without being loaded,
    or be loaded while its contents are stale - either way, remembering that you
    "installed it" tells you nothing.
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
        elif _rendered(src) != dst.read_bytes():
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
    """The same hostname llmwiki uses in its watermark key.

    Copied verbatim from config.host(). doctor does not import llmwiki, so the
    duplication is unavoidable, but if the two diverge this check ends up
    shouting 'ingest stopped' every single time.
    """
    raw = os.environ.get("LLMWIKI_HOST") or socket.gethostname().split(".")[0]
    return re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower() or "unknown"


def _llmwiki_vault(state: Path) -> Path | None:
    """The vault key from config.toml, or the default. doctor does not import
    llmwiki, so this re-reads the bare minimum."""
    # Relative paths resolve against the directory holding the config. Anchoring
    # them to cwd would give doctor and compile different absolute paths and
    # raise a false replacement alarm.
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
    """Is llmwiki actually recording? This looks at outcome, not registration.

    The hook is fail-open, so a broken one never blocks a session. That silence
    is the danger, so failures are logged and read back here. The nightly job is
    asked the same way - not "is it loaded" but "did it run recently" - because
    claude-mem sat at the newest version and recorded nothing for two months.
    """
    out: list[tuple[str, str, str]] = []
    state = LLMWIKI_STATE
    if not state.is_dir():
        return [("llmwiki-capture", "skip", "llmwiki 상태 디렉터리 없음")]

    errlog = LLMWIKI_ERRLOG
    if errlog.is_file():
        # The log is append-only and nothing prunes it. Without a window a single
        # transient failure stays stale forever, fires a weekly alert, and the
        # human learns to ignore it. That habit is what caused the two-month
        # incident.
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=CAPTURE_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Only count lines whose first field is a timestamp. A line whose head
        # was truncated by a partial write compares greater than any cutoff,
        # because letters sort after digits in ASCII, and so stays a 'recent
        # failure' forever. Learning to ignore a weekly alarm ends in the same
        # place as a false green.
        recent = []
        for ln in errlog.read_text(errors="replace").splitlines():
            head = ln.split("\t", 1)[0]
            if re.match(r"\d{4}-\d{2}-\d{2}T", head) and head >= cutoff:
                recent.append(ln)
        if recent:
            out.append(("llmwiki-capture", "stale",
                        f"훅 실패 {len(recent)}건 (최근 {CAPTURE_WINDOW_DAYS}일) "
                        f"— 마지막: {recent[-1][:110]}"))

    # Is the watermark keeping up with claude-mem? A gap means ingest stopped.
    # Only this machine's key is read. max() would let a synced value from
    # another machine, or an old key left behind by a hostname change, hide our
    # stall - someone else's newest value reports "ingest current" while we
    # ingested nothing at all.
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
                # The watermark is ahead of the db. A claude-mem reinstall or a
                # db restore restarts ids at 1, and ingest's
                # WHERE s.id > watermark then matches nothing ever after.
                # Left negative it cannot cross the threshold, so it reads as
                # 'ingest current', and session-capture is green because the new
                # db records fine.
                out.append(("llmwiki-capture", "stale",
                            f"워터마크({watermark})가 db 최신 id({newest})보다 앞선다 — "
                            f"db 가 교체됐다. 적재가 영구히 멈춘 상태이므로 "
                            f"state.json 의 워터마크를 리셋해야 한다"))
                behind = None
            # A fixed threshold alone hides a stall on a new machine. Under 200
            # rows in the db, ingesting nothing still fails to cross it and
            # reads as healthy, and it stays quiet until the db grows. Take
            # whichever of the absolute value and the ratio is stricter.
            limit = min(200, max(10, newest // 4))
            if behind is None:
                pass
            elif behind > limit:
                out.append(("llmwiki-capture", "stale",
                            f"적재가 {behind}세션 밀렸다 (워터마크 {watermark} / 최신 {newest})"))
            else:
                out.append(("llmwiki-capture", "ok",
                            f"적재 최신 (뒤처짐 {behind}세션)"))

    # Does the vault the config points at match the vault actually in use? Back
    # when this was switched by env var only, the CLI wrote to one side while
    # the hooks and launchd wrote to the other, and the vault silently split in
    # two. config.toml is the answer now, but an old env var left in the shell
    # can still send the CLI alone somewhere else.
    env_vault = os.environ.get("LLMWIKI_VAULT")
    if env_vault:
        out.append(("llmwiki-capture", "stale",
                    f"LLMWIKI_VAULT 가 셸에 설정돼 있다 ({env_vault}) — 훅과 launchd 는 "
                    "이 값을 보지 못한다. config.toml 의 vault 키를 쓰고 환경변수를 지워라"))

    # Things that live only in the vault. They are not rebuilt from events, so
    # losing the vault loses these too. Confirmed by measurement - after
    # changing the path and running compile, notes outside GEN and the task
    # pages quietly disappeared.
    vault = _llmwiki_vault(state)

    # compile emits the replacement warning to stderr once and that is it. If
    # the nightly job noticed first, that one line went into ~/Library/Logs/llmwiki.err
    # and every later run is silent. Comparing the last compiled vault that
    # state remembers against the vault the config points at keeps the weekly
    # check showing it.
    try:
        last = str(json.loads((state / "state.json").read_text()).get("vault", "") or "")
    except Exception:
        last = ""
    if last and vault and last != str(vault.resolve()):
        out.append(("llmwiki-capture", "stale",
                    f"마지막으로 컴파일한 볼트는 {last} 인데 설정은 {vault} 를 가리킨다 — "
                    f"직접 쓴 글과 tasks/ 는 옛 볼트에만 있다"))

    # Is there content left in the replaced old vault? This is asked instead of
    # an approval step - delete or merge it and this goes quiet by itself, and
    # it only reports while something is still there.
    try:
        stranded = json.loads((state / "state.json").read_text()).get("vaults_previous", []) or []
    except Exception:
        stranded = []
    current = str(vault.resolve()) if vault else ""
    for previous in [v for v in stranded if v and v != current]:
        old_vault = Path(previous)
        # Looking at .md only would read a vault holding just bases/*.base or
        # hand-added attachments as "empty". If anything at all remains after
        # excluding the stamp file and directories, there is something to lose.
        # The current vault may sit inside the old one (e.g. ~/x/vault →
        # ~/x/vault/wiki). Walking the old path would then pick up files of the
        # live vault, and "move or delete it" would mean deleting the live vault
        # - an alarm that can never be cleared. Nothing under the current vault
        # is counted.
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
        # A task page is T-0001-title.md when it has a title and T-0001.md when
        # it does not (tasks.py:59). Splitting on '-' and joining the first two
        # pieces turns the latter into 'T-0001.md', which never again matches a
        # binding and reports a healthy state as an orphan.
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

    # Does the viewer actually respond? The process can be alive while the port
    # is dead, and back when it ran inside tmux it quietly vanished whenever the
    # window was closed.
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

    # Did the nightly job run recently?
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
    """Claude Code stamps .orphaned_at but never deletes anything.

    `claude plugin prune` only looks at dependency plugins and leaves the
    version cache alone. It keeps piling up for a local plugin whose version is
    bumped on every edit. This only reports - deletion is irreversible and a
    running session may be reading that path.
    """
    if not CACHE_ROOT.is_dir():
        return [("orphaned-cache", "skip", "캐시 루트 없음")]

    out: list[tuple[str, str, str]] = []

    # Temp trees left behind by an interrupted install. Installing a directory
    # source makes Claude Code copy the whole repo into temp_local_*, and if the
    # process dies mid-copy it just stays. Measured: one dev repo left 49GB
    # behind and free disk fell to 3.3GB. Nothing references them, so deleting
    # is safe.
    temps = [d for d in CACHE_ROOT.glob("temp_local_*") if d.is_dir()]
    if temps:
        size = sum(f.stat().st_size for d in temps for f in d.rglob("*") if f.is_file())
        out.append(("orphaned-cache", "stale",
                    f"중단된 설치 잔해 {len(temps)}개 {size // 1024 // 1024}MB — "
                    f"참조되지 않는다. rm -rf {CACHE_ROOT}/temp_local_*"))

    # The version cache is three levels: marketplace/plugin/version. An
    # .orphaned_at at a shallower or deeper path is another tool's marker and is
    # not counted.
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
    """Is the same repository checked out independently in two places?

    claude.sh clones ui-clone-skills into ~/.local/share, but development tends
    to happen in ~/Documents. On this machine the former is a symlink to the
    latter so there is only one, but on a new machine each can end up an
    independent clone. Then a fix on one side never reaches the other, and the
    tool quietly reads the old one.

    Joined by a symlink means one and the same thing, so that is not reported.
    """
    # The dev checkout path gets renamed - ui-skills did in fact become
    # ui-clone-skills. Hardcoding a single name means comparing nothing from
    # then on while quietly passing. Scan the candidates and use the one that
    # exists.
    checkouts = [Path.home() / "Documents/ui-clone-skills",
                 Path.home() / "Documents/ui-skills"]
    dev = next((p for p in checkouts if p.is_dir()), None)
    if dev is None:
        # Emitting no line at all is indistinguishable from "checked, no
        # problem". State the fact that nothing was checked.
        return [("duplicate-checkout", "skip",
                 "개발 체크아웃을 찾지 못했다: "
                 + ", ".join(str(p) for p in checkouts))]
    out = []

    # Look at the path that actually feeds the plugin. Hardcoding the name means
    # that when the marketplace points at a third path, only an irrelevant pair
    # that happens to agree gets compared and ok is emitted. Measured: the
    # source was a detached copy at ~/.local/share/ui-clone-skills-claude-src
    # (neither git nor a symlink) with plugin.json at 0.7.25, while the dev
    # checkout was 0.7.26. Later commits never reach the plugin.
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
    """Several versions left in the cache mean an old one may still be used."""
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
    """Was the directory-source plugin delivered, and does the cache match it?

    `claude plugin install` copies the declared source path into the cache and
    the runtime reads only that copy. Two things confirmed by measurement:

    - Top-level symlinks are not followed. Register a symlink projection as the
      source and the install reports success while creating nothing in the
      cache.
    - `.gitignore` is not applied. Everything in the source is copied.

    So "installed" and "delivered" are different facts, and this check looks at
    the latter. `claude plugin details` reads the marketplace manifest, so it
    prints a normal skill list even when the cache is empty — it cannot be used
    as evidence.
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

        # The source in marketplace.json decides how this is judged. Pointing at
        # a subpath makes Claude Code copy that part into the cache, so the cache
        # can go stale. Pointing at the repo root with './' references the source
        # directly and an empty cache is normal. Measured: dotfiles-local is
        # './plugins/local-skills' and has 19 in the cache; voidmatcha is './'
        # and has 0 in the cache, yet plugin details sees 4 skills.
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
            # The manifest declares the name. It can differ from the directory
            # name - the plugin inside ui-skills/ is in fact named
            # ui-clone-skills.
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
    """Read the install targets and pinned URLs straight from skills.sh.

    Duplicating the list makes the two copies diverge. skills.sh is the one
    declaration.
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
    """Has a pinned upstream skill been modified locally?

    skills.sh now backs up before overwriting, but a backup appearing at all is
    itself the signal to "decide whether to push this upstream".
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
    """Pinning is safe, but leaving a pin forever is drift of its own."""
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
        except Exception as exc:  # one dead check still emits the rest
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
