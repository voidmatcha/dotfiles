#!/usr/bin/env python3
"""Build code-server URLs for git worktrees or arbitrary folders."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlparse

DEFAULT_PORT = "8443"
LOCAL_FALLBACK = "http://127.0.0.1:8088"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def tailscale_host() -> str:
    override = os.environ.get("CODE_SERVER_TAILSCALE_HOST", "").strip().rstrip(".")
    if override:
        return override

    status = run(["tailscale", "status", "--json"])
    if status.returncode == 0 and status.stdout.strip():
        try:
            dns = ((json.loads(status.stdout).get("Self") or {}).get("DNSName") or "").strip().rstrip(".")
            if dns:
                return dns
        except json.JSONDecodeError:
            pass

    ip = run(["tailscale", "ip", "-4"])
    if ip.returncode == 0:
        return ip.stdout.strip().splitlines()[0] if ip.stdout.strip() else ""
    return ""


def local_bind_base() -> str:
    cfg = Path.home() / ".config/code-server/config.yaml"
    addr = ""
    try:
        for line in cfg.read_text().splitlines():
            if line.startswith("bind-addr:"):
                addr = line.split(":", 1)[1].strip()
                break
    except FileNotFoundError:
        pass
    if addr.startswith("0.0.0.0:"):
        addr = "127.0.0.1:" + addr.split(":", 1)[1]
    return f"http://{addr}" if addr else LOCAL_FALLBACK


def tailscale_serve_base(local_base: str) -> str:
    """Return the public Serve URL proxying the configured code-server bind."""
    status = run(["tailscale", "serve", "status", "--json"])
    if status.returncode != 0 or not status.stdout.strip():
        return ""
    try:
        payload = json.loads(status.stdout)
        web = payload.get("Web") or {}
        tcp_config = payload.get("TCP") or {}
    except json.JSONDecodeError:
        return ""

    target = urlparse(local_base)
    target_host = target.hostname or ""
    target_port = target.port
    for public, config in web.items():
        handlers = (config or {}).get("Handlers") or {}
        for handler in handlers.values():
            proxy = (handler or {}).get("Proxy") or ""
            parsed = urlparse(proxy)
            proxy_host = parsed.hostname or ""
            same_loopback = {target_host, proxy_host} <= {"127.0.0.1", "localhost"}
            if target_port == parsed.port and (target_host == proxy_host or same_loopback):
                port = public.rsplit(":", 1)[-1]
                protocol = tcp_config.get(port) or {}
                scheme = "https" if protocol.get("HTTPS") else "http"
                return f"{scheme}://{public}"
    return ""


def base_url() -> str:
    explicit = os.environ.get("CODE_SERVER_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    local_base = local_bind_base().rstrip("/")
    detected = tailscale_serve_base(local_base)
    if detected:
        return detected
    host = tailscale_host()
    if host:
        port = os.environ.get("CODE_SERVER_TAILSCALE_PORT", DEFAULT_PORT).strip() or DEFAULT_PORT
        return f"https://{host}:{port}"
    return local_base


def git_root(path: Path) -> Path | None:
    result = run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return None


def parse_worktrees(root: Path) -> list[dict[str, str]]:
    result = run(["git", "worktree", "list", "--porcelain"], cwd=root)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "git worktree list failed")
    records: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            if cur:
                records.append(cur)
                cur = {}
            continue
        key, _, value = line.partition(" ")
        cur[key] = value or "true"
    if cur:
        records.append(cur)
    return [r for r in records if "worktree" in r and "bare" not in r]


def folder_url(path: Path, base: str) -> str:
    return f"{base}/?folder={quote(str(path.resolve()), safe='')}"


def workspace_url(root: Path, base: str) -> str:
    records = parse_worktrees(root)
    if not records:
        raise SystemExit("no git worktrees found")
    folders = []
    for record in records:
        path = Path(record["worktree"]).resolve()
        branch = record.get("branch", "").removeprefix("refs/heads/") or "detached"
        folders.append({"name": f"{path.name} [{branch}]", "path": str(path)})
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "agent-worktrees"
    cache_root.mkdir(parents=True, exist_ok=True)
    first = Path(records[0]["worktree"]).resolve()
    ws = cache_root / f"{first.name}.worktrees.code-workspace"
    ws.write_text(json.dumps({"folders": folders, "settings": {"git.openRepositoryInParentFolders": "always"}}, indent=2))
    return f"{base}/?workspace={quote(str(ws), safe='')}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".", help="Folder or git worktree path")
    parser.add_argument("--all", action="store_true", help="Build a multi-root workspace URL for all git worktrees")
    parser.add_argument("--base", action="store_true", help="Print only the detected code-server base URL")
    args = parser.parse_args(argv)

    base = base_url()
    if args.base:
        print(base)
        return 0

    path = Path(args.path).expanduser().resolve()
    if args.all:
        root = git_root(path)
        if root is None:
            raise SystemExit(f"not inside a git repo: {path}")
        print(workspace_url(root, base))
    else:
        print(folder_url(path, base))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
