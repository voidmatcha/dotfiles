---
name: dotfiles-verify
description: "Verify dotfiles install scripts, plugin manifests, hooks, TOML/JSON/plist config, and CI-style smoke checks."
---

# Dotfiles Verify

Run the repo-native verifier instead of ad-hoc checks.

## Workflow

1. From the dotfiles repo root, run the smallest useful check:
   - Quick local validation: `bash scripts/verify.sh --quick`
   - Full smoke validation: `bash scripts/verify.sh --full`
2. Read the output. Fix failures in the smallest relevant file set.
3. Re-run the same command until it passes, then report the exact command and result.

## Notes

- `--quick` covers shell syntax, JSON/TOML/plist parsing, plugin manifests, hook settings, and `git diff --check`.
- `--full` also runs Bats when `bats` is installed.
- Do not claim install safety without fresh verifier output or a stated validation gap.
