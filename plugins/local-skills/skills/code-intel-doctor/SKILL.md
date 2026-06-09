---
name: code-intel-doctor
description: "Diagnose codegraph/serena MCP setup, Codex config, and per-repo indexes when code intelligence is broken or stale."
---

# Code Intel Doctor

Use the repo-local doctor before changing MCP config.

## Workflow

1. Run `python3 scripts/code_intel_doctor.py` from the dotfiles repo root.
   - Pass a target repo when needed: `python3 scripts/code_intel_doctor.py /path/to/repo`
2. Check the reported config, live install, and per-repo index statuses.
3. If a dependency is missing, prefer documented setup commands already present in this dotfiles repo.
4. Re-run the doctor after any fix and report status with remaining gaps.
