#!/usr/bin/env python3
"""Bridge purplemux (web tmux multiplexer) and cmux (native GUI) sessions.

purplemux owns tmux sessions named pt-ws-* on the dedicated `purple` socket;
its web UI only shows sessions it created itself. cmux surfaces are plain
Ghostty PTYs with no tmux underneath. So synchronization only works in one
direction: purplemux creates the session, cmux attaches to it as a second
tmux client. An existing cmux PTY can never be mirrored — only its Claude
conversation can be resumed elsewhere via `claude --resume`.

Subcommands:
  list                       purple-socket sessions + their attached clients
  attach <session> [--name N] [--no-focus]
                             open a cmux workspace attached to the session
  attach --all               attach every pt-ws-* session 1:1
  handoff <project-path> [--limit N]
                             recent Claude session ids for that path, with a
                             ready-to-paste `claude --resume` command
"""

import argparse
import json
import os
import re
import subprocess
import sys

SOCKET = "purple"


def tmux(*args, check=True):
    return subprocess.run(
        ["tmux", "-L", SOCKET, *args],
        capture_output=True, text=True, check=check,
    ).stdout


def list_sessions():
    try:
        out = tmux("list-sessions", "-F",
                   "#{session_name}\t#{t:session_created}\t#{session_attached}")
    except subprocess.CalledProcessError:
        print("purplemux-bridge: no purple-socket tmux server running "
              "(is purplemux up? launchctl kickstart -k gui/$UID/com.user.purplemux)")
        return 1
    rows = []
    for line in out.splitlines():
        name, created, attached = line.split("\t")
        clients = tmux("list-clients", "-t", name, "-F",
                       "#{client_tty}", check=False).split()
        rows.append((name, created, attached, ", ".join(clients) or "-"))
    if not rows:
        print("purplemux-bridge: purple socket is up but has no sessions.")
        return 0
    headers = ("SESSION", "CREATED", "ATTACHED", "CLIENT TTYS")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for r in rows:
        print(fmt.format(*r))
    print("\nattach one:  python3 scripts/purplemux_bridge.py attach <SESSION>")
    return 0


def session_names():
    out = tmux("list-sessions", "-F", "#{session_name}", check=False)
    return [s for s in out.split() if s]


def attach(session, name=None, focus=True):
    if session not in session_names():
        print(f"purplemux-bridge: no such session on purple socket: {session}",
              file=sys.stderr)
        return 2
    cmd = [
        "cmux", "new-workspace",
        "--name", name or f"pmux {session}",
        "--command", f"tmux -L {SOCKET} attach-session -t {session}",
        "--focus", "true" if focus else "false",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = (res.stdout + res.stderr).strip()
    print(f"{session}: {out}")
    return res.returncode


def attach_all(focus):
    names = [s for s in session_names() if s.startswith("pt-ws-")]
    if not names:
        print("purplemux-bridge: no pt-ws-* sessions to attach.")
        return 0
    rc = 0
    for i, s in enumerate(names):
        # only focus the first workspace; avoid focus ping-pong
        rc |= attach(s, focus=focus and i == 0)
    return rc


def flatten_project_path(path):
    return re.sub(r"[/.]", "-", os.path.abspath(path))


def handoff(path, limit):
    proj_dir = os.path.expanduser(
        os.path.join("~/.claude/projects", flatten_project_path(path)))
    if not os.path.isdir(proj_dir):
        print(f"purplemux-bridge: no Claude project history at {proj_dir}",
              file=sys.stderr)
        return 2
    files = sorted(
        (f for f in os.listdir(proj_dir) if f.endswith(".jsonl")),
        key=lambda f: os.path.getmtime(os.path.join(proj_dir, f)),
        reverse=True,
    )[:limit]
    if not files:
        print("purplemux-bridge: no sessions recorded for this path.")
        return 0
    import datetime
    print(f"Recent Claude sessions for {os.path.abspath(path)}:")
    for f in files:
        full = os.path.join(proj_dir, f)
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full))
        size_kb = os.path.getsize(full) // 1024
        print(f"  {f[:-6]}  {mtime:%m-%d %H:%M}  {size_kb}KB")
    newest = files[0][:-6]
    print("\nPaste into a purplemux tab (create the tab in the purplemux UI"
          " — externally created sessions don't show up there):")
    print(f"  cd {os.path.abspath(path)} && claude --resume {newest}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    ap_at = sub.add_parser("attach")
    ap_at.add_argument("session", nargs="?")
    ap_at.add_argument("--all", action="store_true")
    ap_at.add_argument("--name")
    ap_at.add_argument("--no-focus", action="store_true")
    ap_ho = sub.add_parser("handoff")
    ap_ho.add_argument("path")
    ap_ho.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "list":
        sys.exit(list_sessions())
    if args.cmd == "attach":
        if args.all:
            sys.exit(attach_all(focus=not args.no_focus))
        if not args.session:
            ap.error("attach requires a session name or --all")
        sys.exit(attach(args.session, args.name, focus=not args.no_focus))
    if args.cmd == "handoff":
        sys.exit(handoff(args.path, args.limit))


if __name__ == "__main__":
    main()
