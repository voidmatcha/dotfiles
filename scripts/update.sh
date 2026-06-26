#!/bin/bash
set -euo pipefail
# shellcheck disable=SC2034 # consumed by scripts/lib/common.sh after source.
TAG="update"
# shellcheck source=scripts/lib/common.sh
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# scripts/update.sh — bring this machine current, skipping anything already done.
#
#   1. git pull   latest dotfiles (skipped if the tree has uncommitted work).
#                 Configs are symlinks into this repo, so a pull alone makes
#                 ~/.zshrc etc. live immediately.
#   2. install.sh --upgrade   the full idempotent setup, where each sub-script
#                 ALSO bumps its own tool versions (brew upgrade, uv tool upgrade,
#                 oh-my-zsh / plugin pulls, codex + oh-my-codex). One pass — no
#                 separate version list to keep in sync, so "update" is just
#                 install.sh --upgrade by construction (nothing is left out).
#
#   scripts/update.sh           pull + install.sh --upgrade
#   scripts/update.sh --check   preview only (install.sh --dry-run --upgrade)
#   scripts/update.sh --no-pull  skip the git pull step
#
# Honors DRY_RUN. claude-code (the running app / cask) is left for deliberate
# upgrade. Per-tool failures warn and continue (see each sub-script).

APPLY=true
DO_PULL=true
for arg in "$@"; do
  case "$arg" in
    --check) APPLY=false ;;
    --no-pull) DO_PULL=false ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/update.sh [--check] [--no-pull]
  (default)   git pull + install.sh --upgrade (idempotent setup + version bumps)
  --check     preview only; change nothing
  --no-pull   skip the git pull step
USAGE
      exit 0
      ;;
    *) warn "unknown argument: $arg"; exit 2 ;;
  esac
done
$DRY_RUN && APPLY=false

# 1) refresh the dotfiles checkout (symlinked configs then go live immediately)
if ! $DO_PULL; then
  info "git pull: skipped (--no-pull)"
elif ! command -v git &>/dev/null || ! git -C "$DOTFILES_DIR" rev-parse --is-inside-work-tree &>/dev/null; then
  warn "git pull skipped (no git / not a repo)"
elif [ -n "$(git -C "$DOTFILES_DIR" status --porcelain 2>/dev/null)" ]; then
  warn "dotfiles has uncommitted changes — skipping git pull (commit or stash to refresh)"
elif $APPLY; then
  info "git pull --ff-only (latest dotfiles)"
  git -C "$DOTFILES_DIR" pull --ff-only || warn "git pull failed (continuing)"
else
  info "[check] would: git -C $DOTFILES_DIR pull --ff-only"
fi

# 2) full idempotent setup + per-tool version upgrades
if $APPLY; then
  info "install.sh --non-interactive --upgrade (setup + version upgrades; skips what's current)"
  bash "$DOTFILES_DIR/install.sh" --non-interactive --upgrade || warn "install.sh reported errors (continuing)"
else
  info "install.sh --dry-run --upgrade (preview — no changes)"
  bash "$DOTFILES_DIR/install.sh" --dry-run --upgrade || true
fi

info "done"
