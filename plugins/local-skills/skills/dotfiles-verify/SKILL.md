---
name: dotfiles-verify
description: "Verify dotfiles install scripts, plugin manifests, hooks, TOML/JSON/plist config, and CI-style smoke checks."
---

# Dotfiles Verify

Run the repo-native verifier instead of ad-hoc checks.

## Workflow

Resolve the checkout explicitly; never assume the caller's cwd:

```bash
DOTFILES_DIR="${DOTFILES_DIR:-$HOME/work/dotfiles}"
test -f "$DOTFILES_DIR/scripts/verify.sh"
```

1. Run the smallest useful check:
   - Quick local validation: `bash "$DOTFILES_DIR/scripts/verify.sh" --quick`
   - Full smoke validation: `bash "$DOTFILES_DIR/scripts/verify.sh" --full`
2. Read the output. Fix failures in the smallest relevant file set.
3. Re-run the same command until it passes, then report the exact command and result.

For a skill description, hook policy, script output, selection rule, or side-effect
change, add a failure-derived positive and negative regression fixture before the
implementation. Static parsing alone does not prove behavior; do not claim completion
until the affected artifact has actually executed against both paths.

## Notes

- `--quick` covers shell/Python syntax, ShellCheck when installed, Python unit tests, skill/plugin metadata, JSON/TOML/plist parsing, hook settings, and `git diff --check`.
- `--full` requires ShellCheck and Bats, then runs the complete Bats suite.
- Do not claim install safety without fresh verifier output or a stated validation gap.
