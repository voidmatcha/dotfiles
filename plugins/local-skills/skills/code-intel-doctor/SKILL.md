---
name: code-intel-doctor
description: "Diagnose codegraph/serena MCP setup, Codex config, and per-repo indexes when code intelligence is broken or stale."
---

# Code Intel Doctor

Use the repo-local doctor before changing MCP config.

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
test -f "$DOTFILES_DIR/scripts/code_intel_doctor.py"
```

1. Run `python3 "$DOTFILES_DIR/scripts/code_intel_doctor.py"`.
   - Pass a target repo when needed: `python3 "$DOTFILES_DIR/scripts/code_intel_doctor.py" /path/to/repo`.
   - For automation, add `--json`; add `--strict` to exit nonzero when commands, config, indexes, or codegraph status are unhealthy.
   - `--strict` treats missing or malformed `reindexRecommended`, `pendingChanges`, and `worktreeMismatch` status fields as failures rather than assuming a clean index.
2. Check the reported config, live install, and per-repo index statuses.
3. If a dependency is missing, prefer documented setup commands already present in this dotfiles repo.
4. Re-run the doctor after any fix and report status with remaining gaps.
