---
name: agent-usage-audit
description: "Audit installed Claude/Codex agents, skills, commands, and recent session usage to decide what to prune, keep, or route."
---

# Agent Usage Audit

Prefer the deterministic local audit script before making recommendations.

## Workflow

1. Run `python3 scripts/agent_usage_audit.py` from the dotfiles repo root.
2. Use the report to separate:
   - installed local assets,
   - recent usage signals,
   - gaps where install exists but usage is absent or unproven.
3. Recommend additions or removals only from observed patterns plus explicit user goals.

## Privacy boundary

The script reports counts and shortened paths only. Do not paste transcript contents, prompts, or private project text unless the user explicitly asks and it is safe.
