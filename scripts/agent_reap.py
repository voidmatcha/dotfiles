#!/usr/bin/env python3
"""Find (and optionally kill) runaway/orphaned processes left by dead agent sessions.

Agent sessions (claude/codex/omx loops, headless runners) spawn shell jobs via
heredocs and snapshots. When a session dies mid-flight (API error, kill, crash)
those children get reparented to launchd and can spin at 100% CPU forever with
nobody left to read their output.

Detection rules (every candidate row is tagged with one):
  ORPHAN-INLINE  ppid==1 and the command is an interpreter running inline code
                 (python -c / python - / sh -c / node -e ...). Humans don't
                 launch stdin-script interpreters from launchd; a dead parent
                 shell did.
  AGENT-CHILD    descendant of a live agent process, or spawned via a Claude
                 shell snapshot, pegging the CPU for longer than --min-age.
  ORPHAN-CPU     ppid==1 plain CLI tool (not a .app or system binary) pegging
                 the CPU for longer than --min-age.

Safety:
  - Scan is read-only; killing requires --kill --pids with an explicit list.
  - --kill refuses pids that are not in the current candidate set.
  - Agent main processes (claude/codex/omx/omc/opencode) are never candidates.
  - The process tree this script runs inside is never a candidate.

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
import signal
import subprocess
import sys
import time
from collections import namedtuple

Proc = namedtuple("Proc", "pid ppid pcpu etime user args")

AGENT_NAMES = {"claude", "codex", "omx", "omc", "opencode"}
INLINE_INTERP_RE = re.compile(r"^(?:python[\d.]*|node|sh|zsh|bash|perl|ruby)$", re.I)
INLINE_FLAGS = {"-c", "-e", "-"}
SYSTEM_PREFIXES = ("/System/", "/usr/libexec/", "/sbin/", "/Applications/", "/Library/")
AGENT_SPAWN_MARKERS = (".claude/shell-snapshots", "CODEX_COMPANION_SESSION_ID")
MAX_ANCESTOR_DEPTH = 30


def list_procs():
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pcpu=,etime=,user=,args="],
        capture_output=True, text=True, check=True,
    ).stdout
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            pid, ppid, pcpu = int(parts[0]), int(parts[1]), float(parts[2])
        except ValueError:
            continue
        procs[pid] = Proc(pid, ppid, pcpu, parts[3], parts[4], parts[5])
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


def cwd_of(pid):
    try:
        out = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            if line.startswith("n"):
                return line[1:]
    except Exception:
        pass
    return "?"


def classify(p, anc_chain, procs, threshold, min_age_s, me):
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
    if p.ppid == 1 and inline:
        return "ORPHAN-INLINE"
    if p.pcpu >= threshold and etime_seconds(p.etime) >= min_age_s:
        if any(m in p.args for m in AGENT_SPAWN_MARKERS):
            return "AGENT-CHILD"
        for a in anc_chain:
            anc = procs.get(a)
            if anc and exe_basename(anc) in AGENT_NAMES:
                return "AGENT-CHILD"
        if p.ppid == 1 and not p.args.startswith(SYSTEM_PREFIXES):
            return "ORPHAN-CPU"
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


def scan(threshold, min_age_s):
    procs = list_procs()
    me = getpass.getuser()
    exact, subtree_roots = protected_sets(procs)
    candidates = []
    for p in procs.values():
        anc_chain = ancestors(p.pid, procs)
        if p.pid in exact or subtree_roots & set(anc_chain):
            continue
        rule = classify(p, anc_chain, procs, threshold, min_age_s, me)
        if rule:
            candidates.append((rule, p))
    candidates.sort(key=lambda rp: -rp[1].pcpu)
    return candidates


def print_table(candidates):
    if not candidates:
        print("agent-reap: no candidates found — nothing to clean up.")
        return
    rows = []
    for rule, p in candidates:
        rows.append((
            str(p.pid), rule, f"{p.pcpu:.1f}", p.etime,
            cwd_of(p.pid), p.args[:90],
        ))
    headers = ("PID", "RULE", "%CPU", "ELAPSED", "CWD", "COMMAND")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for r in rows:
        print(fmt.format(*r))
    pids = ",".join(str(p.pid) for _, p in candidates)
    print(f"\n{len(candidates)} candidate(s). To kill after confirming:")
    print(f"  python3 scripts/agent_reap.py --kill --pids {pids}")


def do_kill(candidates, pids, force):
    cand_pids = {p.pid for _, p in candidates}
    rejected = [pid for pid in pids if pid not in cand_pids]
    if rejected:
        print(f"agent-reap: refusing — not in current candidate set: {rejected}",
              file=sys.stderr)
        return 2
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(2)
    survivors = []
    for pid in pids:
        try:
            os.kill(pid, 0)
            survivors.append(pid)
        except ProcessLookupError:
            continue
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
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--kill", action="store_true", help="kill pids given via --pids")
    ap.add_argument("--pids", type=str, default="",
                    help="comma-separated explicit pid allowlist for --kill")
    ap.add_argument("--force", action="store_true",
                    help="escalate to SIGKILL if SIGTERM survivors remain")
    args = ap.parse_args()

    candidates = scan(args.threshold, args.min_age * 60)

    if args.kill:
        if not args.pids:
            ap.error("--kill requires --pids (explicit allowlist by design)")
        pids = [int(x) for x in args.pids.split(",") if x.strip()]
        sys.exit(do_kill(candidates, pids, args.force))

    if args.json:
        print(json.dumps([
            {"pid": p.pid, "rule": rule, "pcpu": p.pcpu, "elapsed": p.etime,
             "cwd": cwd_of(p.pid), "args": p.args}
            for rule, p in candidates
        ], ensure_ascii=False, indent=2))
    else:
        print_table(candidates)


if __name__ == "__main__":
    main()
