---
name: code-intel-doctor
description: Diagnose code intelligence setup for codegraph, serena, MCP server registration, Codex config, or per-repo index readiness. Use when symbol search, code tracing, MCP routing, or codegraph/serena availability seems broken or stale.
---

# Code Intel Doctor

Use the repo-local doctor before changing MCP config.

## Workflow

1. Run `python3 scripts/code_intel_doctor.py` from the dotfiles repo root.
   - Pass a target repo when needed: `python3 scripts/code_intel_doctor.py /path/to/repo`
2. Check the reported config, live install, and per-repo index statuses.
3. If a dependency is missing, prefer documented setup commands already present in this dotfiles repo.
4. Re-run the doctor after any fix and report status with remaining gaps.
