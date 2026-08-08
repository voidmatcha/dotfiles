---
name: agent-reap
description: "Clean up runaway/orphaned agent processes: stuck zip/tail/python/node, high CPU, dead Claude/Codex/OMX sessions."
---

# Agent Reap

Dead agent sessions leave behind heredoc interpreters and shell-snapshot jobs
reparented to launchd, spinning at 100% CPU with nobody left to read their
output. This skill finds them with explainable rules and kills only what the
user explicitly approves.

## Workflow

Resolve the checkout explicitly; never assume the caller's cwd:

```bash
DOTFILES_DIR="${DOTFILES_DIR:-$(
  for l in "$HOME/.zshrc" "$HOME/.agent/AGENTS.md" "$HOME/.claude/settings.json"; do
    t=$(readlink "$l" 2>/dev/null) || continue
    r=$(cd "$(dirname "$t")/.." 2>/dev/null && pwd) || continue
    [ -d "$r/scripts" ] && printf '%s' "$r" && break
  done
)}"
test -f "$DOTFILES_DIR/scripts/agent_reap.py"
```

1. Scan (read-only): `python3 "$DOTFILES_DIR/scripts/agent_reap.py"`.
   - Lower the CPU floor when hunting quieter leaks: `--threshold 30`
   - `--json` for machine-readable output.
2. Show the candidate table to the user. Each row carries a rule tag explaining
   why it was flagged:
   - `ORPHAN-INLINE` — old, high-CPU ppid 1 interpreter running inline code
     (`python -c`, `sh -c`, …); both the CPU and `--min-age` gates must pass.
   - `AGENT-CHILD` — long-running high-CPU descendant of a live agent process
     or a Claude shell-snapshot job.
   - `ORPHAN-CPU` — ppid 1 CLI tool (non-app, non-system) pegging the CPU.
3. Never kill without explicit user confirmation. Present the exact PID list
   (AskUserQuestion works well) — `AGENT-CHILD` rows belong to a session that
   is still alive, so name which session loses the work before asking.
4. Kill only the approved pids:
   `python3 "$DOTFILES_DIR/scripts/agent_reap.py" --kill --pids <approved,comma,separated>`
   - Add `--force` only if SIGTERM survivors remain.
5. Re-run the scan to verify, and report reclaimed CPU.

## Safety properties (already enforced by the script)

- `--kill` refuses any pid not in the current candidate set.
- Agent main processes (claude/codex/omx/omc) are never candidates.
- The script's own session subtree is never a candidate, but sibling agent
  sessions under the same multiplexer (cmux) are still scanned.
