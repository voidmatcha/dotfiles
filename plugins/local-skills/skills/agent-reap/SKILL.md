---
name: agent-reap
description: "Clean up runaway/orphaned/redundant agent processes: stuck zip/tail/python/node, high CPU, memory-hogging or duplicate MCP and language servers, dead Claude/Codex sessions."
---

# Agent Reap

Dead agent sessions leave behind heredoc interpreters and shell-snapshot jobs
reparented to launchd, spinning at 100% CPU with nobody left to read their
output. Live sessions leak too: every MCP reconnect strands the previous MCP
server and its language-server subtree, idle at 0% CPU but still resident.
This skill finds both with explainable rules and kills only what the user
explicitly approves.

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
   - Lower the RSS floor for the memory rule: `--mem-threshold 150` (MB)
   - `--json` for machine-readable output.
2. Read the summary line first. It reports agent-owned RSS next to Chrome's,
   so a small reclaim number is not mistaken for a wrong diagnosis — if Chrome
   dominates, say so instead of hunting for more candidates.
3. Show the candidate table to the user. Each row carries a rule tag explaining
   why it was flagged, and a `SUBTREE` column counting the descendants that
   die alongside it:
   - `ORPHAN-INLINE` — old, high-CPU ppid 1 interpreter running inline code
     (`python -c`, `sh -c`, …); both the CPU and `--min-age` gates must pass.
   - `AGENT-CHILD` — long-running high-CPU descendant of a live agent process
     or a Claude shell-snapshot job.
   - `ORPHAN-CPU` — ppid 1 CLI tool (non-app, non-system) pegging the CPU.
   - `STALE-MCP` — redundant MCP server under a live session: same session,
     binary, argv and cwd as a younger sibling. No CPU gate; these idle at 0%
     while holding a whole language-server subtree resident.
   - `ORPHAN-BROWSER` — `ppid==1` agent browser launcher (`agent-browser`,
     `chrome-devtools-mcp`) still holding a Chrome tree. `ppid==1` already
     proves the session that spawned it is gone.
   - `AGENT-MEM` — agent descendant above `--mem-threshold`, regardless of CPU.

   Memory is the physical footprint Activity Monitor reports, not `ps` RSS.
   macOS compresses and swaps idle processes out, so RSS under-reports a hung
   language server by two orders of magnitude — never diagnose from RSS.
4. Never kill without explicit user confirmation. Present the exact PID list
   (AskUserQuestion works well) — `AGENT-CHILD`, `STALE-MCP` and `AGENT-MEM`
   rows belong to sessions that are still alive, so name which session is
   affected before asking. For `STALE-MCP` say what actually breaks: nothing,
   unless the surviving server is also killed.
5. Kill only the approved pids:
   `python3 "$DOTFILES_DIR/scripts/agent_reap.py" --kill --pids <approved,comma,separated>`
   - Add `--force` only if SIGTERM survivors remain.
6. Re-run the scan to verify, and report reclaimed memory and CPU.

## Safety properties (already enforced by the script)

- `--kill` refuses any pid not in the current candidate set. Descendants of an
  approved pid are terminated with it, since they exist only to serve it.
- `STALE-MCP` always leaves the youngest server of each group alive, so a live
  session never loses its tooling. cwd is part of the group identity: servers
  with identical argv but different working directories are distinct, not
  duplicates.
- Agent main processes (claude/codex/omc) are never candidates.
- The script's own session subtree is never a candidate, but sibling agent
  sessions under the same multiplexer (cmux) are still scanned.
- A browser launched by the user is never a candidate. Agent browsers are
  identified by their throwaway temp profile (`agent-browser-chrome-<uuid>`)
  or launcher binary, never by "is Chrome" — a real browsing session has
  neither and stays out of reach.
