#!/usr/bin/env python3
"""skill_probe.py — observe whether `claude -p` routes to a SPECIFIC target skill.

run_eval.py only detects its own throwaway command name, so when an installed
plugin skill shadows the candidate it scores genuine activations as zero. This
probe instead watches the real `claude -p` stream for the TARGET skill's own
routing (a `Skill` call to `<plugin>:<name>` or a `Read` of the skill's dir),
letting behavioral_check.sh tell a real-skill activation apart from "nothing
triggered" and fail closed (UNVERIFIED -> human gate) when discrimination is not
attributable.

Safety: every mutating tool — Bash, Edit, Write, NotebookEdit, MultiEdit, AND
Task (subagent dispatch, an indirect mutation path) — is denied. In `claude -p`,
`--disallowedTools` blocks EXECUTION, not just auto-approval (verified with a
sentinel: a denied `touch` never created its file), so a triggered agentic skill
cannot modify the tree even in the window before we detect+kill. (Note: an
allowlist does NOT block execution in -p mode — unlisted tools still run — so a
denylist is the correct mechanism here.)

Completeness: we do NOT stop at the first routing. A routing to some OTHER skill
is ignored and we keep scanning for the TARGET until the run's `result` (or the
deadline), so a later target activation is not missed and misread as "clear".

Usage:
  skill_probe.py --queries-file q.json --target-skill NAME [--skill-dir DIR]
                 [--runs 1] [--timeout 45]
    q.json: ["query one", "query two", ...]

Output (stdout JSON):
  {"probes": [{"query": "...", "runs": [
      {"target_fired": true, "tools": [{"tool":"Skill","target":"local-skills:NAME"}], "error": false}]}]}

Exit 0 on a completed probe; exit 2 if claude is missing or every run errored
(caller treats that as UNVERIFIED, never a pass).
"""

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROUTING_TOOLS = ("Skill", "Read")  # the only tools that activate a skill
# Mutation vectors denied for the probe. Task is included: a skill could dispatch
# a subagent that mutates. Verified that --disallowedTools blocks execution in -p.
# (MultiEdit is not a known tool in current Claude builds — passing it to --disallowedTools only
# emits a "matches no known tool" warning; all live mutation/dispatch vectors below stay denied.)
DENY_TOOLS = ["Bash", "Edit", "Write", "NotebookEdit", "Task"]


def _target_of(tool_name: str, tool_input: dict) -> str:
    """The routing target of a tool_use: the skill name or read path, else ''."""
    if tool_name == "Skill":
        return str(tool_input.get("skill", ""))
    if tool_name == "Read":
        return str(tool_input.get("file_path", ""))
    return ""


def _matches_target(tool: str, target: str, target_skill: str, skill_dir: str) -> bool:
    """True only if a routing tool IS an ACTIVATION of the skill under test.

    Tool-aware: the `Skill` tool routed to "<plugin>:<name>" (or bare name) activates
    the skill; a `Read` activates it ONLY if it reads the skill's EXACT SKILL.md. A
    Read of any other file (or a Skill-name pattern appearing in a Read path) is
    ordinary inspection, not activation, so it must not match. Paths are realpath-
    normalized so a relative skill_dir still matches the model's absolute Read path.
    """
    if not target:
        return False
    if tool == "Skill" and target.split(":")[-1].strip() == target_skill:
        return True
    if tool == "Read" and skill_dir:
        want = os.path.realpath(skill_dir.rstrip("/") + "/SKILL.md")
        if os.path.realpath(target) == want:
            return True
    return False


def _parse(line: str):
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def probe_once(query: str, timeout: int, target_skill: str, skill_dir: str) -> dict:
    """Run one `claude -p` and report whether the TARGET skill routes during the run.

    Returns {"target_fired": bool, "tools": [{tool,target}...], "error": bool}.
    Returns early (killing the subprocess) the moment the target routes; otherwise
    scans until the final `result`. error=True means could-not-measure (no result
    before the deadline / spawn failure) -> caller fails closed.
    """
    cmd = [
        "claude", "-p", query,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--disallowedTools", *DENY_TOOLS,
    ]
    # Strip CLAUDECODE so a nested `claude -p` is allowed (the guard is only for
    # interactive terminal conflicts; programmatic subprocess use is safe).
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )
    except OSError:
        return {"target_fired": False, "tools": [], "error": True}

    state = {"buffer": "", "pending": None, "acc": "", "saw_result": False}
    seen = []  # all routing tools observed (for the report)
    recorded = set()  # (tool, target) already in `seen`: the stream and assistant paths both surface
                      # the SAME tool_use, so dedup to avoid ~2x inflation of the evidence list.
    deadline = time.time() + timeout

    def record(name, inp):
        """Record a routing tool (deduped); return a hit dict if it IS the target, else None."""
        target = _target_of(name, inp)
        key = (name, target)
        if key not in recorded:
            recorded.add(key)
            seen.append({"tool": name, "target": target})
        if _matches_target(name, target, target_skill, skill_dir):
            return {"target_fired": True, "tools": seen, "error": False}
        return None

    def handle(event):
        """Process one stream event. Return a final dict to stop early, else None."""
        etype = event.get("type")
        if etype == "stream_event":
            se = event.get("event", {})
            st = se.get("type", "")
            if st == "content_block_start":
                cb = se.get("content_block", {})
                if cb.get("type") == "tool_use" and cb.get("name") in ROUTING_TOOLS:
                    state["pending"], state["acc"] = cb.get("name"), ""
            elif st == "content_block_delta" and state["pending"] is not None:
                d = se.get("delta", {})
                if d.get("type") == "input_json_delta":
                    state["acc"] += d.get("partial_json", "")
                    try:
                        inp = json.loads(state["acc"])
                    except json.JSONDecodeError:
                        inp = None
                    if isinstance(inp, dict) and _target_of(state["pending"], inp):
                        got = record(state["pending"], inp)
                        state["pending"] = None
                        if got:
                            return got
            elif st in ("content_block_stop", "message_stop") and state["pending"] is not None:
                try:
                    inp = json.loads(state["acc"])
                except json.JSONDecodeError:
                    inp = {}
                got = record(state["pending"], inp if isinstance(inp, dict) else {})
                state["pending"] = None
                if got:
                    return got
        elif etype == "assistant":  # fallback: complete tool_use input
            for item in event.get("message", {}).get("content", []):
                if item.get("type") == "tool_use" and item.get("name") in ROUTING_TOOLS:
                    got = record(item.get("name"), item.get("input", {}) or {})
                    if got:
                        return got
        elif etype == "result":
            # Only a SUCCESSFUL result counts as "measured". An error result
            # (auth/API failure, max-turns, execution error) leaves saw_result False
            # so the run is reported error=True -> the caller fails closed to unexec.
            if event.get("subtype") == "success" and not event.get("is_error"):
                state["saw_result"] = True
        return None

    def drain():
        """Parse every complete line in the buffer. Return a final dict or None."""
        while "\n" in state["buffer"]:
            line, state["buffer"] = state["buffer"].split("\n", 1)
            event = _parse(line)
            if event is None:
                continue
            got = handle(event)
            if got is not None:
                return got
        return None

    try:
        while time.time() < deadline:
            if proc.poll() is None:
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if not ready:
                    continue
                chunk = os.read(proc.stdout.fileno(), 8192)
                if not chunk:
                    break
                state["buffer"] += chunk.decode("utf-8", errors="replace")
            else:
                rest = proc.stdout.read()
                if rest:
                    state["buffer"] += rest.decode("utf-8", errors="replace")
            got = drain()
            if got is not None:
                return got
            if proc.poll() is not None and "\n" not in state["buffer"]:
                break
        # Final drain on EVERY exit path (EOF, deadline, process exit). Some streams omit
        # the trailing newline on the last line, so normalize it through the SAME parser —
        # this resolves a final result, assistant, OR stream_event routing uniformly.
        if state["buffer"] and not state["buffer"].endswith("\n"):
            state["buffer"] += "\n"
        got = drain()
        if got is not None:
            return got
        return {"target_fired": False, "tools": seen, "error": not state["saw_result"]}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries-file", required=True)
    ap.add_argument("--target-skill", required=True)
    ap.add_argument("--skill-dir", default="")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=45)
    args = ap.parse_args()

    if shutil.which("claude") is None:
        print(json.dumps({"error": "claude CLI not found"}))
        return 2

    queries = json.loads(Path(args.queries_file).read_text())
    probes = []
    any_ok = False
    for q in queries:
        runs = []
        fired = False
        for _ in range(max(1, args.runs)):
            r = probe_once(q, args.timeout, args.target_skill, args.skill_dir)
            runs.append(r)
            if not r["error"]:
                any_ok = True
            if r["target_fired"]:
                fired = True
        probes.append({"query": q, "runs": runs})
        # Shadow proven -> stop (no need to probe remaining positives). Until then we
        # probe EVERY positive, so a shadow that only manifests on a later query is
        # not missed. Per-run `error` flags are reported so the caller fails closed
        # on any could-not-measure run rather than reading it as "clear".
        if fired:
            break

    print(json.dumps({"probes": probes}))
    return 2 if not any_ok else 0


if __name__ == "__main__":
    sys.exit(main())
