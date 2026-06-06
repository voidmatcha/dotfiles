---
name: cmux-handoff-runner
description: Manage long-running Claude/Codex/OMX work handed off through cmux tabs or surfaces. Use when asked to start, attach, monitor, or recover agent loops in cmux; when cmux tabs appear idle or commands do not execute; or when a multi-step loop must pause for improvement, install, commit, and continue safely.
---

# Cmux Handoff Runner

Use a shell coordinator for long-running loops. Do not rely on a single agent prompt to manage many future iterations.

## Core contract

1. **Coordinator owns sequencing.** A shell script or terminal driver launches one bounded agent task at a time, polls it, and decides the next step.
2. **Agents own one unit.** Claude/Codex/OMX should receive only one clone loop, one improvement pass, or one verification pass per launch.
3. **Next step needs evidence.** Continue only after both:
   - a status/marker artifact exists, and
   - the relevant process/tool activity has ended or returned to an idle prompt.
4. **Improve before continuing.** After each failed or incomplete loop: inspect artifacts, make one generalizable skill/hook/script fix, run targeted tests, run local install, then commit/push if the user requested persistence.

## Cmux runtime preflight

After creating or selecting a terminal surface, verify it is a real running terminal before sending work:

```bash
cmux debug-terminals | grep -A8 'surface:<N>'
cmux top --workspace workspace:<W> --processes --flat --format tsv
```

A usable terminal has all of these:

- `runtime=1`
- `ghostty=` is not `nil`
- `tty=` is not `nil`
- `cmux top` shows at least `login` plus a shell process under the surface

Reject or recreate surfaces with `runtime=0`, `ghostty=nil`, or `tty=nil`. They may accept `cmux send` without executing anything.

## Smoke test before handoff

Before starting Claude/Codex/OMX, prove command delivery with a file marker:

```bash
MARKER=".omx/artifacts/cmux-smoke-$(date -u +%Y%m%d-%H%M%S).txt"
cmux send --workspace workspace:<W> --surface surface:<S> \
  "cd '$PWD' && date -u > '$MARKER' && echo READY >> '$MARKER'\n"
sleep 3
test -s "$MARKER" && cat "$MARKER"
```

If the marker is missing, do not launch the agent there. Use an existing healthy surface or rebuild the workspace.

## Status artifact schema

Use repo-local ignored artifacts, commonly `.omx/artifacts/<run>/`:

- `coordinator-status.md`: current step, active surface, PID, last poll time, next action
- `<engine>-loop-<NN>-status.md`: commands run, gate reached, blocker, fidelity gaps, recommendation
- `improvement-<engine>-<NN>.md`: changed files, rationale, tests, install result, commit/push status
- `state.jsonl`: append-only events for launches, polls, exits, improvements, installs, commits
- `coordinator.lock`: lock file containing PID, host, cwd, run id, and startedAt

## Safe launch pattern

- Start with `git status --short` and `git rev-list --left-right --count HEAD...@{u}` when an upstream exists.
- Run required local install before each loop when the task depends on freshly installed skills/plugins/hooks.
- Verify install provenance when relevant: installed plugin/skill path, local root marker, hook config, and version/commit used by the agent.
- Record the exact command in the status file before launching.
- Prefer `cmux send ... "<command>\n"` on a verified existing terminal over creating many new tabs.
- Clean up only stale processes tied to the current run/component name. Do not kill unrelated agent sessions.
- Use a lock file or `flock` before launching a coordinator. If the lock PID is alive, attach/inspect it instead of starting a second coordinator.
- Add `trap` cleanup for temporary files and child processes that belong to the current run id.
- Write a heartbeat timestamp on every poll so a later session can distinguish slow work from a dead coordinator.
- When commit/push is required, record `git status --short`, `git diff --stat`, commit SHA, upstream ahead/behind count, and push result.
- Run Claude/Codex/OMX agent CLIs in the foreground of a real TTY. Do not background the agent process itself; if heartbeat is needed, run a separate background heartbeat watcher while the agent stays foreground.

## Minimal coordinator guardrails

Use these invariants in any shell coordinator:

```bash
RUN_ID="${RUN_ID:-$(date -u +%Y%m%d-%H%M%S)}"
ART="${ART:-.omx/artifacts/cmux-handoff-$RUN_ID}"
LOCK="$ART/coordinator.lock"
mkdir -p "$ART"

if [ -f "$LOCK" ] && kill -0 "$(awk -F= '/^pid=/{print $2}' "$LOCK")" 2>/dev/null; then
  echo "coordinator already running: $LOCK" >&2
  exit 2
fi

{
  echo "pid=$$"
  echo "host=$(hostname)"
  echo "cwd=$PWD"
  echo "run_id=$RUN_ID"
  echo "startedAt=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$LOCK"

trap 'echo "endedAt=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOCK"' EXIT
```

## Recovery heuristics

Treat the handoff as stalled when any of these is true:

- status file mtime is older than the polling SLA and no child process is active;
- a newly created cmux terminal has `runtime=0`;
- a command appears in the terminal but no smoke marker or child process appears;
- an agent changed files but did not write the required status marker;
- a helper process runs past its expected bound with no artifact mtime movement.
- a second coordinator or agent was launched for the same run/component while the first is still active.
- an agent exits immediately with `stdin is not a terminal`; this usually means the coordinator backgrounded a TTY-bound CLI.

Recovery order:

1. Read current status, git diff, active processes, and cmux runtime state.
2. Preserve useful local changes; do not overwrite them.
3. If a cmux terminal has `runtime=0`, try `cmux refresh-surfaces`; if it still has no runtime, close that surface and reuse a known-good surface.
4. Stop only stale processes scoped to the current component/run. Prefer exact PID files, command substrings with the component/run id, or process groups created by the coordinator.
5. Convert the discovered failure into a bounded coordinator check or script fix.
6. Reinstall, verify, commit/push if requested, then resume with the next single bounded unit.

## Completion checklist

Before declaring a handoff loop complete, capture:

- final status marker for every requested unit;
- no live scoped child processes;
- local install/projection evidence when hooks or skills were changed;
- test or smoke evidence for every improvement;
- git clean/ahead-behind state, or an explicit list of remaining local changes;
- stale cmux surfaces/servers cleaned up or intentionally left with a reason.

## What not to do

- Do not ask a long-running agent prompt to run many future loops without an external coordinator.
- Do not treat `cmux new-workspace OK` as proof that the terminal is executable.
- Do not use status markers alone as completion proof while the agent/process is still active.
- Do not start the next loop until improvement/install/commit requirements for the prior loop are satisfied.
- Do not leave a hidden background coordinator, Vite server, browser session, or agent process running without recording it in the status artifact.
