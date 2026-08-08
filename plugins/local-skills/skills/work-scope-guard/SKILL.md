---
name: work-scope-guard
description: "Inspect work-scope safety reminders for company/work dirs, sensitive URLs, internal data routing, and hook overlays."
---

# Work Scope Guard

Use the tracked hook and keep it generic; do not hardcode secrets.

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
test -f "$DOTFILES_DIR/configs/hooks/work-scope-guard.sh"
```

1. Inspect `$DOTFILES_DIR/configs/hooks/work-scope-guard.sh` and `$DOTFILES_DIR/configs/claude-settings.json`.
2. Verify the hook is linked by `$DOTFILES_DIR/install.sh` into `~/.claude/hooks/work-scope-guard.sh`.
3. Test with a synthetic hook payload and a temporary work-like cwd when changing behavior.
4. Keep output advisory and fail-open. This guard must remind, not block ordinary tools.

## Safety

- No tokens, emails, internal hostnames, or private URLs in the public hook.
- Company-specific overlays belong in `company/` or local ignored files.
