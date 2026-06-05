---
name: cmux-doctor
description: Diagnose cmux, purplemux, tmux, multi-pane orchestration, terminal surface routing, or Codex cmux skill installation problems in this dotfiles setup. Use when panes, tabs, surfaces, sockets, or workspace automation behave unexpectedly.
---

# cmux Doctor

Diagnose the local multiplexing stack before changing launch scripts.

## Workflow

1. Identify the layer: `cmux`, `purplemux`, `tmux`, Codex cmux skill, or LaunchAgent.
2. Run cheap checks first:
   - `command -v cmux purplemux tmux`
   - `tmux list-sessions` when tmux is involved
   - `launchctl print gui/$(id -u)/com.user.purplemux` on macOS LaunchAgent issues
3. For Codex skill install problems, run `bash scripts/codex.sh --dry-run` or `bash scripts/skills.sh codex` as appropriate.
4. Preserve existing sessions; do not kill panes/sessions unless explicitly requested.
