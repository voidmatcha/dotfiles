---
name: purplemux-bridge
description: Bridge purplemux (web/phone tmux multiplexer, dedicated `purple` socket) and cmux (native GUI) sessions — attach pt-ws tmux sessions 1:1 into cmux workspaces, or hand an existing cmux Claude session off to purplemux via claude --resume. Use when the user wants the same session visible on desktop and phone, asks to attach/sync purplemux and cmux sessions ("퍼플먹스", "세션 동기화", "폰에서 이어서"), or wants to continue a cmux session from the purplemux web UI.
---

# Purplemux Bridge

Why a bridge is needed (and which direction works):

- purplemux owns tmux sessions named `pt-ws-*` on the dedicated `purple`
  socket. Its web UI keeps its own registry — sessions created externally on
  that socket do NOT appear in the UI.
- cmux surfaces are plain Ghostty PTYs with no tmux underneath, so an
  existing cmux session can never be mirrored into purplemux.
- Therefore: **purplemux creates the session, cmux attaches to it** as a
  second tmux client. Both stay fully synchronized (same session, two
  clients). The reverse direction is conversation handoff only
  (`claude --resume`), not terminal mirroring.

## Workflow

All commands run from the dotfiles repo root.

1. Inspect: `python3 scripts/purplemux_bridge.py list`
   — purple-socket sessions with attached client ttys. A session that
   already shows a client tty may already have a cmux workspace attached;
   don't double-attach without asking.
2. Attach one session into a cmux workspace:
   `python3 scripts/purplemux_bridge.py attach <pt-ws-...> [--name N] [--no-focus]`
   Or all pt-ws sessions 1:1: `python3 scripts/purplemux_bridge.py attach --all`
3. Hand an existing cmux Claude session off to purplemux:
   `python3 scripts/purplemux_bridge.py handoff <project-path>`
   — lists recent Claude session ids for that path and prints the
   `claude --resume` command. The user must create the tab in the
   purplemux UI first and paste the command there; ask them to close the
   original cmux session afterwards so two copies don't diverge.

## Caveats

- tmux mirrors the smallest attached client; if the cmux pane and the phone
  view differ a lot in size, the larger one gets letterboxed.
- If `list` reports no purple-socket server, purplemux isn't running:
  `launchctl kickstart -k gui/$(id -u)/com.user.purplemux`.
- Detach from the cmux side with `tmux detach` (purplemux's tmux.conf has no
  prefix key) or just close the surface — the session survives either way.
