---
name: dotfiles-sync
description: "Apply dotfiles changes to this machine and judge the LLM tooling layer — plugin drift, hook registration, skill pins, dirty state, and whether local or repo should win. Use for 'dotfiles 반영해줘', 'dotfiles 업데이트', 'sync dotfiles', 'skill 최신으로', 'hook 등록 확인', or when install/update output needs interpreting. Do not use for plain verification (use dotfiles-verify) or for editing unrelated code."
---

# Dotfiles Sync

Scripts execute and verify. This skill interprets and decides. Never hand-roll an
install command — delegate to the repo's own entry points.

```bash
DOTFILES_DIR="${DOTFILES_DIR:-$(
  for l in "$HOME/.zshrc" "$HOME/.agent/AGENTS.md" "$HOME/.claude/settings.json"; do
    t=$(readlink "$l" 2>/dev/null) || continue
    r=$(cd "$(dirname "$t")/.." 2>/dev/null && pwd) || continue
    [ -d "$r/scripts" ] && printf '%s' "$r" && break
  done
)}"
test -f "$DOTFILES_DIR/scripts/doctor.sh"
```

## Workflow

1. **Read state before changing it.**
   - `bash "$DOTFILES_DIR/scripts/doctor.sh"` — health plus the `-- llm tooling --`
     section (plugin drift, marketplace age, session capture, codex hooks, skill pins)
   - `git -C "$DOTFILES_DIR" status --porcelain` — uncommitted work blocks `git pull`
   - `bash "$DOTFILES_DIR/scripts/update.sh" --check` — preview, changes nothing
2. **Decide direction per divergence.** See "Which side wins" below.
3. **Apply** with `bash "$DOTFILES_DIR/scripts/update.sh"`. Nothing else.
4. **Verify** with `bash "$DOTFILES_DIR/scripts/verify.sh" --quick` and re-run
   `doctor.sh`. Compare the `llm tooling` section against step 1.
5. **Report restarts.** Source `scripts/lib/sync-map.sh` and call
   `restart_notes_since <last-applied-commit>`. Never restart an agent session
   yourself — an interrupted session cannot be undone.

## Which side wins

The repo is the source of truth only where the installed path is a symlink into it.

- **Symlinked** (`~/.zshrc`, `~/.claude/settings.json`, `~/.agent/AGENTS.md`,
  `plugins/local-skills/**`): editing the live file *is* editing the repo. There is
  nothing to reconcile — just commit it.
- **Real files** (`~/.codex/config.toml`, `~/.codex/hooks.json`, `~/.codex/AGENTS.md`):
  both the machine and the scripts write here. A local edit that is not represented
  in the repo will be absent on the next machine and may be lost when a script
  rewrites the file. When the local copy is ahead, **capture it back into the repo
  first**, then apply. Do not let a script overwrite an unrecorded local change.
- **Both changed**: stop and ask. Do not merge silently.

## Judgment this skill owns

Scripts cannot make these calls, which is why they land here:

- **Version drift is a proxy; capture is the outcome.** `session-capture` showing
  `codex: 0 sessions in 7d` means the tooling is broken even when every version reads
  current. Treat a missing outcome as more urgent than a stale version.
- **Whether an upgrade is worth taking.** Read release notes and open issues for
  anything far behind before recommending it.
- **Back up state before upgrading its owner.** `claude-mem` carries a multi-hundred-MB
  database; snapshot it before a version jump.
- **Repair versus reinstall.** Idempotent re-runs fix drift, not corruption. When a
  plugin cache holds several versions, a symlink points somewhere unexpected, or a
  hook is registered but rejected at runtime, uninstall and reinstall through the
  repo's scripts rather than patching around it.
- **Whether a pinned SHA should move.** `skill-pin` entries are deliberate. Bumping
  one is a decision, not maintenance.

## Landing rule

Anything learned here must end up in a script, a check, or a test before the session
ends. A finding that lives only in the transcript is gone next session — that is how
claude-mem sat two months behind while every script reported success.

## Notes

- `update.sh` refuses to pull with a dirty checkout. That guard is correct; commit or
  stash rather than bypassing it.
- `doctor.sh` exits non-zero only on `fail`, not on `warn`. Read the warnings.
- Do not claim a sync succeeded without fresh `doctor.sh` output taken after the run.
