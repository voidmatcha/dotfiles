#!/usr/bin/env python3
"""Find (and optionally kill) runaway/orphaned processes left by dead agent sessions.

Agent sessions (claude/codex loops, headless runners) spawn shell jobs via
heredocs and snapshots. When a session dies mid-flight (API error, kill, crash)
those children get reparented to launchd and can spin at 100% CPU forever with
nobody left to read their output.

Detection rules (every candidate row is tagged with one):
  ORPHAN-INLINE  ppid==1, old and high-CPU, and the command is an interpreter
                 running inline code (python -c / python - / sh -c / node -e
                 ...). Age and CPU gates avoid flagging legitimate launchd jobs.
  AGENT-CHILD    descendant of a live agent process, or spawned via a Claude
                 shell snapshot, pegging the CPU for longer than --min-age.
  ORPHAN-CPU     ppid==1 plain CLI tool (not a .app or system binary) pegging
                 the CPU for longer than --min-age.
  STALE-MCP      redundant MCP server under a live agent session: same session,
                 same binary, same argv, same cwd, and not the youngest of its
                 group. Reconnects leave the older ones resident but
                 unreferenced, each holding its own language-server subtree.
                 No CPU gate — these leak memory while idle at 0%.
  ORPHAN-BROWSER ppid==1 agent browser launcher (agent-browser,
                 chrome-devtools-mcp) older than --min-age, holding a whole
                 Chrome tree. No CPU gate: ppid==1 already proves no live
                 session owns it.
  AGENT-MEM      agent descendant above --mem-threshold for longer than
                 --min-age, regardless of CPU.

Memory is measured as physical footprint (what Activity Monitor's Memory
column shows), not ps RSS. Under pressure macOS compresses and swaps idle
processes out, so a hung language server can report 12 MB of RSS while
actually costing 1.9 GB — RSS would hide exactly the leaks worth finding.

Safety:
  - Scan is read-only; killing requires --kill --pids with an explicit list.
  - --kill refuses pids that are not in the current candidate set; descendants
    of an approved pid die with it, since they exist only to serve it.
  - Agent main processes (claude/codex/omc) are never candidates.
  - The process tree this script runs inside is never a candidate.
  - A browser you launched yourself is never a candidate: it has no agent
    ancestor, so no rule reaches it. Only agent-spawned browsers qualify.

Usage:
  python3 scripts/agent_reap.py                      # scan, print table
  python3 scripts/agent_reap.py --threshold 30
  python3 scripts/agent_reap.py --json
  python3 scripts/agent_reap.py --kill --pids 123,456 [--force]
"""

import argparse
import getpass
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

Proc = namedtuple("Proc", "pid ppid pcpu mem etime user args")
MEM_UNITS = {"B": 1 / 1024, "K": 1, "M": 1024, "G": 1024 ** 2, "T": 1024 ** 3}
MEM_TOKEN_RE = re.compile(r"^([\d.]+)([BKMGT])?[-+]?$")

AGENT_NAMES = {"claude", "codex", "omc"}
MCP_MARKER_RE = re.compile(
    r"(?:start-mcp-server|\bmcp[-_]server\b|chrome-devtools-mcp)"
)
CHROME_RE = re.compile(r"Google Chrome|Chromium", re.I)
# Launchers that own a throwaway automation browser. Their temp profile
# (agent-browser-chrome-<uuid>) self-identifies the tree as agent-spawned, so
# detection never has to guess from ancestry — which is exactly what breaks
# when the launcher gets reparented to launchd.
AGENT_BROWSER_RE = re.compile(
    r"(?:(?:^|/)agent-browser(?:\s|$)|chrome-devtools-mcp|agent-browser-chrome-)"
)
INLINE_INTERP_RE = re.compile(r"^(?:python[\d.]*|node|sh|zsh|bash|perl|ruby)$", re.I)
INLINE_FLAGS = {"-c", "-e", "-"}
SYSTEM_PREFIXES = ("/System/", "/usr/libexec/", "/sbin/", "/Applications/", "/Library/")
AGENT_SPAWN_MARKERS = (".claude/shell-snapshots", "CODEX_COMPANION_SESSION_ID")
MAX_ANCESTOR_DEPTH = 30


def parse_mem_token(token):
    """top's MEM column ('1922M', '3920K', '2.1G') to KB."""
    m = MEM_TOKEN_RE.match(token)
    if not m:
        return None
    return int(float(m.group(1)) * MEM_UNITS.get(m.group(2) or "K", 1))


def footprint_map():
    """Physical memory footprint per pid, in KB.

    ps reports RSS, which counts only pages currently resident. Under memory
    pressure macOS compresses and swaps idle processes out, so a hung language
    server can report 12 MB of RSS while actually costing 1.9 GB — the number
    Activity Monitor's Memory column shows. top's MEM column is that same
    footprint, so we prefer it and fall back to RSS only if top is unavailable.
    """
    try:
        out = subprocess.run(
            ["top", "-l", "1", "-stats", "pid,mem"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    mem, started = {}, False
    for line in out.splitlines():
        if not started:
            started = line.lstrip().startswith("PID")
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        kb = parse_mem_token(parts[1])
        if kb is not None:
            mem[pid] = kb
    return mem


def list_procs():
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pcpu=,rss=,etime=,user=,args="],
        capture_output=True, text=True, check=True,
    ).stdout
    footprints = footprint_map()
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
            pcpu, rss = float(parts[2]), int(parts[3])
        except ValueError:
            continue
        procs[pid] = Proc(
            pid, ppid, pcpu, footprints.get(pid, rss), parts[4], parts[5], parts[6]
        )
    return procs


def etime_seconds(etime):
    days = 0
    if "-" in etime:
        d, etime = etime.split("-", 1)
        days = int(d)
    fields = [int(x) for x in etime.split(":")]
    while len(fields) < 3:
        fields.insert(0, 0)
    h, m, s = fields
    return ((days * 24 + h) * 60 + m) * 60 + s


def exe_basename(p):
    return os.path.basename(p.args.split(None, 1)[0]).lower()


def ancestors(pid, procs):
    seen = []
    cur = pid
    for _ in range(MAX_ANCESTOR_DEPTH):
        proc = procs.get(cur)
        if proc is None or proc.ppid in (0, cur):
            break
        cur = proc.ppid
        if cur in (0, 1):
            break
        seen.append(cur)
    return seen


def children_map(procs):
    kids = {}
    for p in procs.values():
        kids.setdefault(p.ppid, []).append(p.pid)
    return kids


def descendants(pid, procs, kids=None):
    kids = kids if kids is not None else children_map(procs)
    out, stack = [], list(kids.get(pid, []))
    seen = {pid}
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        out.append(cur)
        stack.extend(kids.get(cur, []))
    return out


def subtree_mem(pid, procs, kids=None):
    total = procs[pid].mem if pid in procs else 0
    for d in descendants(pid, procs, kids):
        if d in procs:
            total += procs[d].mem
    return total


def session_root(pid, procs):
    """Pid of the nearest claude/codex/omc ancestor, or None."""
    for a in ancestors(pid, procs):
        anc = procs.get(a)
        if anc and exe_basename(anc) in AGENT_NAMES:
            return a
    return None


def is_agent_spawned(p, anc_chain, procs):
    if any(m in p.args for m in AGENT_SPAWN_MARKERS):
        return True
    return any(
        (anc := procs.get(a)) and exe_basename(anc) in AGENT_NAMES
        for a in anc_chain
    )


def find_stale_mcp(procs, min_age_s, me, cwd_lookup=None):
    """Redundant MCP servers under one live agent session.

    A session needs exactly one MCP server per (binary, argv, cwd). Reconnects
    leave the older ones resident but unreferenced, each dragging its own
    language-server subtree along. Group by session and identity, keep the
    youngest, and offer the rest. cwd is part of the identity because argv
    alone can be byte-identical across genuinely different projects (serena's
    --project-from-cwd).
    """
    servers = [
        p for p in procs.values()
        if p.user == me
        and exe_basename(p) not in AGENT_NAMES
        and MCP_MARKER_RE.search(p.args)
        and session_root(p.pid, procs) is not None
    ]
    if cwd_lookup is None:
        batch = cwds_of([p.pid for p in servers])
        cwd_lookup = lambda pid: batch.get(pid, "?")  # noqa: E731
    groups = {}
    for p in servers:
        root = session_root(p.pid, procs)
        groups.setdefault(
            (root, exe_basename(p), p.args, cwd_lookup(p.pid)), []
        ).append(p)

    stale = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: etime_seconds(m.etime))
        for p in members[1:]:
            if etime_seconds(p.etime) >= min_age_s:
                stale.add(p.pid)
    return stale


def agent_owned_pids(procs, me):
    """Every pid an agent is responsible for, including detached browser trees.

    Ancestry alone is not enough: an agent-browser launcher gets reparented to
    launchd when its session dies, so its whole Chrome tree looks unowned.
    Treat such a launcher as a root in its own right.
    """
    kids = children_map(procs)
    owned = set()
    for p in procs.values():
        if p.user != me:
            continue
        detached_browser = p.ppid == 1 and AGENT_BROWSER_RE.search(p.args)
        if session_root(p.pid, procs) is not None or detached_browser:
            owned.add(p.pid)
            owned.update(descendants(p.pid, procs, kids))
    return owned


def memory_summary(procs, me):
    """Agent-owned footprint versus browsers agent-reap deliberately cannot touch."""
    owned = agent_owned_pids(procs, me)
    agent_kb = agent_count = chrome_kb = chrome_count = 0
    for p in procs.values():
        if p.user != me:
            continue
        if p.pid in owned:
            agent_kb += p.mem
            agent_count += 1
        elif CHROME_RE.search(p.args):
            chrome_kb += p.mem
            chrome_count += 1
    return {
        "agent_family_kb": agent_kb,
        "agent_family_count": agent_count,
        "chrome_out_of_reach_kb": chrome_kb,
        "chrome_out_of_reach_count": chrome_count,
    }


def cwds_of(pids):
    """cwd for many pids in one lsof call.

    Per-pid lsof costs ~50ms; the MCP dedup alone asks for a hundred of them.
    """
    pids = [str(p) for p in pids]
    if not pids:
        return {}
    try:
        out = subprocess.run(
            ["lsof", "-a", "-p", ",".join(pids), "-d", "cwd", "-Fpn"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found, cur = {}, None
    for line in out.splitlines():
        if line.startswith("p"):
            try:
                cur = int(line[1:])
            except ValueError:
                cur = None
        elif line.startswith("n") and cur is not None:
            found.setdefault(cur, line[1:])
    return found


def cwd_of(pid):
    return cwds_of([pid]).get(pid, "?")


def classify(p, anc_chain, procs, threshold, min_age_s, me, mem_threshold_kb=None):
    if p.user != me:
        return None
    base = exe_basename(p)
    if base in AGENT_NAMES:
        return None
    tokens = p.args.split()
    inline = (
        len(tokens) >= 2
        and INLINE_INTERP_RE.match(base)
        and tokens[1] in INLINE_FLAGS
    )
    aged = etime_seconds(p.etime) >= min_age_s
    aged_and_hot = p.pcpu >= threshold and aged
    if p.ppid == 1 and inline and aged_and_hot:
        return "ORPHAN-INLINE"
    if p.ppid == 1 and aged and AGENT_BROWSER_RE.search(p.args):
        return "ORPHAN-BROWSER"
    if aged_and_hot:
        if is_agent_spawned(p, anc_chain, procs):
            return "AGENT-CHILD"
        if p.ppid == 1 and not p.args.startswith(SYSTEM_PREFIXES):
            return "ORPHAN-CPU"
    if (
        mem_threshold_kb
        and aged
        and p.mem >= mem_threshold_kb
        and is_agent_spawned(p, anc_chain, procs)
    ):
        return "AGENT-MEM"
    return None


def protected_sets(procs):
    """Protect this script's own ancestry and its enclosing agent session.

    Walk up only to the nearest agent process (claude/codex/...): protecting
    anything above it (cmux, the terminal app) would shield every other
    session running under the same multiplexer from being scanned.
    """
    me_pid = os.getpid()
    chain = ancestors(me_pid, procs)
    exact = set(chain) | {me_pid}
    subtree_roots = {me_pid}
    for pid in chain:
        subtree_roots.add(pid)
        proc = procs.get(pid)
        if proc and exe_basename(proc) in AGENT_NAMES:
            break
    return exact, subtree_roots


def scan(threshold, min_age_s, mem_threshold_kb=None):
    procs = list_procs()
    me = getpass.getuser()
    exact, subtree_roots = protected_sets(procs)
    stale = find_stale_mcp(procs, min_age_s, me)
    candidates = []
    for p in procs.values():
        anc_chain = ancestors(p.pid, procs)
        if p.pid in exact or subtree_roots & set(anc_chain):
            continue
        rule = "STALE-MCP" if p.pid in stale else classify(
            p, anc_chain, procs, threshold, min_age_s, me, mem_threshold_kb
        )
        if rule:
            candidates.append((rule, p))
    kids = children_map(procs)
    candidates.sort(key=lambda rp: -subtree_mem(rp[1].pid, procs, kids))
    return candidates, procs


def print_summary(summary):
    agent_mb = summary["agent_family_kb"] / 1024
    chrome_mb = summary["chrome_out_of_reach_kb"] / 1024
    print(
        f"agent-reap: agent-owned {agent_mb:,.0f} MB "
        f"({summary['agent_family_count']} procs) | "
        f"Chrome {chrome_mb:,.0f} MB "
        f"({summary['chrome_out_of_reach_count']} procs, out of reach)"
    )


def print_table(candidates, procs=None):
    if not candidates:
        print("agent-reap: no candidates found — nothing to clean up.")
        return
    kids = children_map(procs) if procs else None
    cwds = cwds_of([p.pid for _, p in candidates])
    rows = []
    for rule, p in candidates:
        if procs:
            desc = len(descendants(p.pid, procs, kids))
            total_mb = subtree_mem(p.pid, procs, kids) / 1024
            tree = f"+{desc} / {total_mb:,.0f} MB"
        else:
            tree = f"{p.mem / 1024:,.0f} MB"
        rows.append((
            str(p.pid), rule, f"{p.pcpu:.1f}", tree, p.etime,
            cwds.get(p.pid, "?"), p.args[:90],
        ))
    headers = ("PID", "RULE", "%CPU", "SUBTREE", "ELAPSED", "CWD", "COMMAND")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for r in rows:
        print(fmt.format(*r))
    pids = ",".join(str(p.pid) for _, p in candidates)
    interpreter = shlex.quote(sys.executable or "python3")
    script = shlex.quote(str(Path(__file__).resolve()))
    print(f"\n{len(candidates)} candidate(s); SUBTREE counts descendants killed alongside.")
    print("To kill after confirming:")
    print(f"  {interpreter} {script} --kill --pids {pids}")


def do_kill(candidates, pids, force, procs=None):
    cand_pids = {p.pid for _, p in candidates}
    rejected = [pid for pid in pids if pid not in cand_pids]
    if rejected:
        print(f"agent-reap: refusing — not in current candidate set: {rejected}",
              file=sys.stderr)
        return 2
    if procs:
        kids = children_map(procs)
        for pid in list(pids):
            for d in descendants(pid, procs, kids):
                if d not in pids:
                    pids.append(d)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(2)
    survivors = []
    for pid in pids:
        if pid_alive(pid):
            survivors.append(pid)
    if survivors and force:
        for pid in survivors:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(1)
        survivors = [pid for pid in survivors if pid_alive(pid)]
    killed = [pid for pid in pids if pid not in survivors]
    print(f"agent-reap: terminated {killed or 'none'}")
    if survivors:
        hint = "" if force else " (retry with --force to SIGKILL)"
        print(f"agent-reap: still alive: {survivors}{hint}")
        return 1
    return 0


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threshold", type=float, default=50.0,
                    help="%%CPU floor for AGENT-CHILD / ORPHAN-CPU rules (default 50)")
    ap.add_argument("--min-age", type=float, default=10.0,
                    help="minimum elapsed minutes for CPU rules (default 10)")
    ap.add_argument("--mem-threshold", type=float, default=300.0,
                    help="RSS floor in MB for the AGENT-MEM rule (default 300)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--kill", action="store_true", help="kill pids given via --pids")
    ap.add_argument("--pids", type=str, default="",
                    help="comma-separated explicit pid allowlist for --kill")
    ap.add_argument("--force", action="store_true",
                    help="escalate to SIGKILL if SIGTERM survivors remain")
    args = ap.parse_args()

    candidates, procs = scan(
        args.threshold, args.min_age * 60, args.mem_threshold * 1024
    )

    if args.kill:
        if not args.pids:
            ap.error("--kill requires --pids (explicit allowlist by design)")
        pids = [int(x) for x in args.pids.split(",") if x.strip()]
        sys.exit(do_kill(candidates, pids, args.force, procs))

    summary = memory_summary(procs, getpass.getuser())
    kids = children_map(procs)

    if args.json:
        cwds = cwds_of([p.pid for _, p in candidates])
        print(json.dumps({
            "summary": summary,
            "candidates": [
                {"pid": p.pid, "rule": rule, "pcpu": p.pcpu, "mem_kb": p.mem,
                 "subtree_mem_kb": subtree_mem(p.pid, procs, kids),
                 "descendants": len(descendants(p.pid, procs, kids)),
                 "elapsed": p.etime, "cwd": cwds.get(p.pid, "?"), "args": p.args}
                for rule, p in candidates
            ],
        }, ensure_ascii=False, indent=2))
    else:
        print_summary(summary)
        print_table(candidates, procs)


if __name__ == "__main__":
    main()
