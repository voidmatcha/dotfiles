---
name: context-check
description: "Check Claude/Codex/OMX context, cache, headroom, and handover pressure; advise continue, compact, clear, or hand off."
---

# Context Check

Use this skill as an advisory context/cache gate. It should not mutate session state by itself.

## Quick workflow

1. From the dotfiles repo root, run:
   ```bash
   python3 plugins/local-skills/skills/context-check/scripts/context_check.py diagnose --cwd "$PWD"
   ```
2. Read the recommendation and evidence.
3. Apply the policy manually:
   - **continue** — same task, cache/context still healthy enough.
   - **compact** — same task, useful context must be preserved, but cache/context pressure is high.
   - **clear** — new/disposable task or stale context is more harmful than useful.
   - **handover** — switch tool/model/tab, recover from poisoned context, or move work to fresh cmux tabs with ACK/READY.

## Policy

- Prefer same-session continuation while cache is warm and context is not bloated.
- Prefer `/compact` when the same task must continue and important context would be lost by clearing.
- Prefer `/clear` when the task is disposable, done, or a fresh branch would be cleaner than preserving history.
- Prefer `$handover` only when a fresh agent surface is valuable: Claude ↔ OMX/Codex transfer, tab/session closure, stuck/poisoned context, or long-running cmux handoff.
- Never auto-run `/clear`, `/compact`, or `$handover` from the hook; surface the recommendation and let the active agent/user apply it.

## Tool priority

- **Headroom active (`claudeh`/`codexh`/`omxh` or default shell wrappers)**:
  treat Headroom as the primary token/cache mitigation layer.
- **Claude/Codex/OMX with agentsview**: use agentsview for local session-shape and usage evidence; treat it as lower confidence for the current live prompt.
- **ccusage**: useful historical spend signal, not a current-context oracle; run only when explicitly needed (`--include-ccusage`).
- **No tools available**: fall back to Headroom status when present plus local hook state, prompt size, transcript size, idle time, and turn count.

## Availability

- Claude: repo install links `~/.claude/hooks/context-check.sh` and the `local-skills@dotfiles-local` plugin exposes this skill.
- Codex/OMX: `scripts/skills.sh codex` symlinks this skill into `~/.codex/skills/context-check`; use `$context-check` or run the script directly.
