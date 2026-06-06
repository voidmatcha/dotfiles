---
name: purplemux-bridge
description: Bidirectional bridge between purplemux (web/phone tmux multiplexer, dedicated `purple` socket) and cmux (native GUI) — attach live purplemux sessions 1:1 into cmux workspaces, and migrate cmux-only Claude sessions into purplemux tabs via claude --resume. Use when the user wants the same session visible/controllable on desktop and phone, asks to attach/sync purplemux and cmux ("퍼플먹스", "세션 동기화", "양방향", "폰에서 이어서"), or wants cmux sessions to show up in purplemux.
---

# Purplemux Bridge

Why a bridge (and the direction asymmetry):

- purplemux owns tmux sessions `pt-<wsId>-<paneId>-<tabId>` on the `purple`
  socket; its UI registry lives in `~/.purplemux/workspaces.json`. Sessions
  whose workspace id is missing there are **zombies** (tab closed in the UI).
- cmux surfaces are plain Ghostty PTYs — no tmux underneath, so a running
  cmux session can never be PTY-mirrored, only resumed.
- Once a session is tmux-backed, sync IS bidirectional: cmux and the phone
  are two clients of the same session. The asymmetry is only about where a
  session is born — purplemux must create it; cmux attaches.

**Liveness rule (user policy): only sessions alive on BOTH sides get
bridged.** Zombie purplemux sessions are skipped; dead Claude sessions are
never resumed automatically.

## Workflow

All commands from the dotfiles repo root.

1. Inspect: `python3 scripts/purplemux_bridge.py list`
   — TAB column says live/ZOMBIE, RUNNING shows the foreground command.
2. purplemux → cmux: `... attach <session>` or `... attach --all`
   (live sessions only; `--include-dead` to override, `--no-focus` available).
3. cmux → purplemux: `... migrate` (no args = discovery table of live claude
   processes: cmux-only vs already tmux-backed, with resolved or candidate
   session ids). Then `... migrate --pid <PID> [--session-id <ID>]` or
   `... migrate --all`.
   - Requires one **idle live** purplemux tab per migrated session; if short,
     ask the user to create tabs in the purplemux UI (one tap) and re-run.
   - After migrating, remind the user to close the ORIGINAL cmux surfaces —
     two copies of the same conversation diverge. Closing kills the original
     process, so confirm with the user first.
4. Manual handoff helper: `... handoff <project-path>` prints recent session
   ids and a ready-to-paste resume command.

## Caveats

- tmux mirrors the smallest attached client; a phone view letterboxes the
  desktop view while attached.
- purplemux has no public API to create tabs (creation is implicit when its
  web client connects); don't try to fake `pt-*` sessions or edit
  `~/.purplemux/workspaces.json` — the server holds state in memory.
- If `list` reports no purple-socket server:
  `launchctl kickstart -k gui/$(id -u)/com.user.purplemux`.
- Detach from the cmux side with `tmux detach` or close the surface — the
  session survives either way.
