#!/usr/bin/env python3
"""Bridge purplemux (web tmux multiplexer) and cmux (native GUI) sessions.

purplemux owns tmux sessions named pt-<wsId>-<paneId>-<tabId> on the dedicated
`purple` socket; its web UI shows only tabs in its own registry
(~/.purplemux/workspaces.json). cmux surfaces are plain Ghostty PTYs with no
tmux underneath. Mutual sync therefore means: tmux is the single source of
truth, purplemux creates the session, cmux attaches as a second client.

Liveness rule: only sessions that are alive on BOTH sides get bridged.
A pt-* session whose workspace id is missing from workspaces.json is a
zombie (tab was closed in the UI) — skipped unless --include-dead.

Subcommands:
  list                       purple-socket sessions + live/busy/client state
  attach <session> [--name N] [--no-focus]
  attach --all               attach every LIVE pt-* session 1:1 into cmux
  migrate [--pid N | --all] [--session-id ID]
                             move cmux-only Claude sessions into idle live
                             purplemux tabs via `claude --resume` (no args:
                             dry-run discovery table)
  handoff <project-path> [--limit N]
                             recent Claude session ids + resume command
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

SOCKET = "purple"
WORKSPACES_FILE = os.path.expanduser("~/.purplemux/workspaces.json")
SHELLS = {"zsh", "bash", "fish", "sh", "-zsh", "-bash", "login"}
AGENT_HELPER_MARKERS = ("--output-format", "--input-format")


def tmux(*args, check=True):
    return subprocess.run(
        ["tmux", "-L", SOCKET, *args],
        capture_output=True, text=True, check=check,
    ).stdout


def live_workspace_ids():
    try:
        with open(WORKSPACES_FILE) as f:
            data = json.load(f)
        return {ws["id"] for ws in data.get("workspaces", [])}
    except (OSError, ValueError, KeyError):
        return set()


def session_ws_id(name):
    # pt-<wsId>-<paneId>-<tabId> where each id is like ws-XXXXXX
    m = re.match(r"^pt-(ws-[^-]+)-", name)
    return m.group(1) if m else None


def sessions_info():
    """[{name, live, cmd, clients}] for every session on the purple socket."""
    out = tmux("list-sessions", "-F", "#{session_name}", check=False)
    live_ws = live_workspace_ids()
    infos = []
    for name in out.split():
        cmd = tmux("list-panes", "-t", name, "-F",
                   "#{pane_current_command}", check=False).strip() or "?"
        clients = tmux("list-clients", "-t", name, "-F",
                       "#{client_tty}", check=False).split()
        ws = session_ws_id(name)
        infos.append({
            "name": name,
            "live": ws in live_ws if ws else False,
            "busy": cmd.split()[0] not in SHELLS if cmd != "?" else False,
            "cmd": cmd.splitlines()[0],
            "clients": clients,
        })
    return infos


def cmd_list():
    infos = sessions_info()
    if not infos:
        print("purplemux-bridge: no purple-socket sessions "
              "(is purplemux up? launchctl kickstart -k gui/$UID/com.user.purplemux)")
        return 0
    rows = [(s["name"],
             "live" if s["live"] else "ZOMBIE",
             s["cmd"] if s["busy"] else f"idle ({s['cmd']})",
             ", ".join(s["clients"]) or "-")
            for s in infos]
    headers = ("SESSION", "TAB", "RUNNING", "CLIENT TTYS")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for r in rows:
        print(fmt.format(*r))
    return 0


def attach(session, name=None, focus=True, include_dead=False):
    infos = {s["name"]: s for s in sessions_info()}
    info = infos.get(session)
    if info is None:
        print(f"purplemux-bridge: no such session on purple socket: {session}",
              file=sys.stderr)
        return 2
    if not info["live"] and not include_dead:
        print(f"purplemux-bridge: {session} is a zombie (tab closed in the "
              "purplemux UI) — pass --include-dead to attach anyway",
              file=sys.stderr)
        return 2
    res = subprocess.run([
        "cmux", "new-workspace",
        "--name", name or f"pmux {session}",
        "--command", f"tmux -L {SOCKET} attach-session -t {session}",
        "--focus", "true" if focus else "false",
    ], capture_output=True, text=True)
    print(f"{session}: {(res.stdout + res.stderr).strip()}")
    return res.returncode


def attach_all(focus):
    targets = [s for s in sessions_info()
               if s["name"].startswith("pt-") and s["live"]]
    if not targets:
        print("purplemux-bridge: no live pt-* sessions to attach.")
        return 0
    rc = 0
    for i, s in enumerate(targets):
        rc |= attach(s["name"], focus=focus and i == 0)
    return rc


# ---------- migrate: cmux-only Claude sessions -> purplemux tabs ----------

def my_ancestor_pids():
    pids, cur = set(), os.getpid()
    procs = {int(p): int(pp) for p, pp in
             (line.split() for line in subprocess.run(
                 ["ps", "-axo", "pid=,ppid="],
                 capture_output=True, text=True).stdout.splitlines())}
    for _ in range(30):
        pids.add(cur)
        cur = procs.get(cur, 0)
        if cur in (0, 1):
            break
    return pids


def purple_pane_ttys():
    out = tmux("list-panes", "-a", "-F", "#{pane_tty}", check=False)
    return {t.replace("/dev/", "") for t in out.split()}


def claude_mains():
    """Live interactive claude CLI processes: [{pid, etime, tty, cwd}]."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,etime=,tty=,args="],
        capture_output=True, text=True).stdout
    mains = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, etime, tty, args = parts
        exe = os.path.basename(args.split(None, 1)[0])
        if exe != "claude" or any(m in args for m in AGENT_HELPER_MARKERS):
            continue
        mains.append({"pid": int(pid), "etime": etime, "tty": tty})
    for m in mains:
        cwd = subprocess.run(
            ["lsof", "-a", "-p", str(m["pid"]), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, timeout=5).stdout
        m["cwd"] = next((l[1:] for l in cwd.splitlines() if l.startswith("n")), "?")
    return mains


def session_id_from_children(pid):
    out = subprocess.run(["ps", "-axo", "ppid=,args="],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0] == str(pid):
            m = re.search(r"COMPANION_SESSION_ID='([0-9a-f-]{36})'", parts[1])
            if m:
                return m.group(1)
    return None


def recent_session_ids(cwd, limit=3):
    proj = os.path.expanduser(
        os.path.join("~/.claude/projects", re.sub(r"[/.]", "-", cwd)))
    if not os.path.isdir(proj):
        return []
    files = sorted((f for f in os.listdir(proj) if f.endswith(".jsonl")),
                   key=lambda f: os.path.getmtime(os.path.join(proj, f)),
                   reverse=True)[:limit]
    return [(f[:-6],
             datetime.datetime.fromtimestamp(
                 os.path.getmtime(os.path.join(proj, f))).strftime("%m-%d %H:%M"))
            for f in files]


def migrate_candidates():
    mine = my_ancestor_pids()
    pane_ttys = purple_pane_ttys()
    cands = []
    for m in claude_mains():
        if m["pid"] in mine:
            m["state"] = "this session — excluded"
        elif m["tty"].replace("/dev/", "") in pane_ttys:
            m["state"] = "already tmux-backed"
        else:
            m["state"] = "cmux-only"
        m["session_id"] = session_id_from_children(m["pid"])
        cands.append(m)
    return cands


def idle_live_tabs():
    return [s["name"] for s in sessions_info()
            if s["name"].startswith("pt-") and s["live"] and not s["busy"]]


def cmd_migrate(pid, do_all, session_id, yes):
    cands = migrate_candidates()
    movable = [c for c in cands if c["state"] == "cmux-only"]
    if pid is None and not do_all:
        print("Live claude sessions:")
        for c in cands:
            sid = c["session_id"] or "?"
            print(f"  pid {c['pid']:>6}  up {c['etime']:>11}  {c['cwd']}  "
                  f"[{c['state']}]  session={sid}")
            if c["state"] == "cmux-only" and not c["session_id"]:
                for s, mt in recent_session_ids(c["cwd"]):
                    print(f"      candidate session: {s}  ({mt})")
        if movable:
            print("\nmigrate one: ... migrate --pid <PID> [--session-id <ID>]"
                  "\nmigrate all: ... migrate --all")
        return 0

    targets = movable if do_all else [c for c in movable if c["pid"] == pid]
    if not targets:
        print("purplemux-bridge: nothing to migrate "
              "(no matching cmux-only claude session)", file=sys.stderr)
        return 2
    tabs = idle_live_tabs()
    if len(tabs) < len(targets):
        print(f"purplemux-bridge: need {len(targets)} idle live purplemux "
              f"tab(s), found {len(tabs)} — create more tabs in the purplemux "
              "UI (phone/web) and re-run.", file=sys.stderr)
        return 2
    rc = 0
    for c, tab in zip(targets, tabs):
        sid = session_id if (session_id and not do_all) else c["session_id"]
        if not sid:
            recent = recent_session_ids(c["cwd"], limit=1)
            if not recent:
                print(f"pid {c['pid']}: no session id resolvable — skipped",
                      file=sys.stderr)
                rc = 1
                continue
            sid = recent[0][0]
        cmd = f"cd {c['cwd']!r} && claude --resume {sid}"
        tmux("send-keys", "-t", tab, cmd, "Enter")
        print(f"pid {c['pid']} -> {tab}: {cmd}")
    if rc == 0 and targets:
        print("\nResumed copies are now tmux-backed (visible in purplemux + "
              "attachable in cmux).\nClose the ORIGINAL cmux surfaces once "
              "you've confirmed the resumed sessions, or two copies will "
              "diverge.")
    return rc


def cmd_handoff(path, limit):
    sessions = recent_session_ids(os.path.abspath(path), limit)
    if not sessions:
        print(f"purplemux-bridge: no Claude session history for {path}",
              file=sys.stderr)
        return 2
    print(f"Recent Claude sessions for {os.path.abspath(path)}:")
    for sid, mtime in sessions:
        print(f"  {sid}  {mtime}")
    print("\nPaste into an idle purplemux tab (or run `migrate`):")
    print(f"  cd {os.path.abspath(path)} && claude --resume {sessions[0][0]}")
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
    ap_at.add_argument("--include-dead", action="store_true")
    ap_mi = sub.add_parser("migrate")
    ap_mi.add_argument("--pid", type=int)
    ap_mi.add_argument("--all", action="store_true")
    ap_mi.add_argument("--session-id")
    ap_mi.add_argument("--yes", action="store_true")
    ap_ho = sub.add_parser("handoff")
    ap_ho.add_argument("path")
    ap_ho.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "list":
        sys.exit(cmd_list())
    if args.cmd == "attach":
        if args.all:
            sys.exit(attach_all(focus=not args.no_focus))
        if not args.session:
            ap.error("attach requires a session name or --all")
        sys.exit(attach(args.session, args.name,
                        focus=not args.no_focus,
                        include_dead=args.include_dead))
    if args.cmd == "migrate":
        sys.exit(cmd_migrate(args.pid, args.all, args.session_id, args.yes))
    if args.cmd == "handoff":
        sys.exit(cmd_handoff(args.path, args.limit))


if __name__ == "__main__":
    main()
