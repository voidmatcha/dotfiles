---
name: work-scope-guard
description: Configure, inspect, or explain local work-scope safety reminders for company/work directories, sensitive URLs, internal data routing, or hook-based context overlays. Use when asked to prevent accidental public-tool use on work projects or to add a company/work guardrail.
---

# Work Scope Guard

Use the tracked hook and keep it generic; do not hardcode secrets.

## Workflow

1. Inspect `configs/hooks/work-scope-guard.sh` and `configs/claude-settings.json`.
2. Verify the hook is linked by `install.sh` into `~/.claude/hooks/work-scope-guard.sh`.
3. Test with a synthetic hook payload and a temporary work-like cwd when changing behavior.
4. Keep output advisory and fail-open. This guard must remind, not block ordinary tools.

## Safety

- No tokens, emails, internal hostnames, or private URLs in the public hook.
- Company-specific overlays belong in `company/` or local ignored files.
