---
name: agent-reap
description: Scan for and clean up runaway or orphaned processes left behind by dead agent sessions — stuck zip/tail jobs, orphaned python/node inline scripts pegging the CPU after a claude/codex/omx loop or headless session dies. Use when the machine feels hot or loud, CPU is pegged near 100%, a loop session crashed mid-run, or the user asks to clean up processes (e.g. "프로세스 정리", "고아 프로세스", "CPU 왜 이래", "fans are spinning").
---

# Agent Reap

Dead agent sessions leave behind heredoc interpreters and shell-snapshot jobs
reparented to launchd, spinning at 100% CPU with nobody left to read their
output. This skill finds them with explainable rules and kills only what the
user explicitly approves.

## Workflow

1. Scan (read-only): `python3 scripts/agent_reap.py` from the dotfiles repo root.
   - Lower the CPU floor when hunting quieter leaks: `--threshold 30`
   - `--json` for machine-readable output.
2. Show the candidate table to the user. Each row carries a rule tag explaining
   why it was flagged:
   - `ORPHAN-INLINE` — ppid 1 interpreter running inline code (`python -c`,
     `sh -c`, …); its parent shell is dead, the work is pure waste.
   - `AGENT-CHILD` — long-running high-CPU descendant of a live agent process
     or a Claude shell-snapshot job.
   - `ORPHAN-CPU` — ppid 1 CLI tool (non-app, non-system) pegging the CPU.
3. Never kill without explicit user confirmation. Present the exact PID list
   (AskUserQuestion works well) — `AGENT-CHILD` rows belong to a session that
   is still alive, so name which session loses the work before asking.
4. Kill only the approved pids:
   `python3 scripts/agent_reap.py --kill --pids <approved,comma,separated>`
   - Add `--force` only if SIGTERM survivors remain.
5. Re-run the scan to verify, and report reclaimed CPU.

## Safety properties (already enforced by the script)

- `--kill` refuses any pid not in the current candidate set.
- Agent main processes (claude/codex/omx/omc/opencode) are never candidates.
- The script's own session subtree is never a candidate, but sibling agent
  sessions under the same multiplexer (cmux) are still scanned.
