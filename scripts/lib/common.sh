#!/bin/bash
# Shared helpers sourced by every script under scripts/.
# Idempotent: safe to source multiple times via the _DOTFILES_COMMON_LOADED guard.

# shellcheck shell=bash

if [ -n "${_DOTFILES_COMMON_LOADED:-}" ]; then
  return 0
fi
_DOTFILES_COMMON_LOADED=1

# DOTFILES_DIR is set by install.sh; provide a fallback for direct script invocation.
# common.sh lives at scripts/lib/common.sh, so the repo root is two levels up.
DOTFILES_DIR="${DOTFILES_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DRY_RUN="${DRY_RUN:-false}"
TAG="${TAG:-dotfiles}"

# Colors (no-op when stdout is not a TTY)
if [ -t 1 ]; then
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[1;33m'
  RED=$'\033[0;31m'
  NC=$'\033[0m'
else
  GREEN='' YELLOW='' RED='' NC=''
fi

info()  { echo "${GREEN}[${TAG}]${NC} $*"; }
warn()  { echo "${YELLOW}[${TAG}]${NC} $*" >&2; }
error() { echo "${RED}[${TAG}]${NC} $*" >&2; }

# run_or_dry "<description>" <cmd> [args...]
# Echoes the command in dry-run mode, executes it otherwise.
run_or_dry() {
  local desc="$1"; shift
  if $DRY_RUN; then
    info "[dry-run] ${desc}: $*"
  else
    "$@"
  fi
}

# link_file "<source>" "<destination>"
# Backs up an existing real file (not symlink) before linking. Honors DRY_RUN.
link_file() {
  local src="$1"
  local dst="$2"

  if $DRY_RUN; then
    info "[dry-run] ln -sf $src -> $dst"
    return 0
  fi

  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    warn "Backing up $dst -> ${dst}.backup"
    mv "$dst" "${dst}.backup"
  fi

  mkdir -p "$(dirname "$dst")"
  ln -sf "$src" "$dst"
  info "Linked: $src -> $dst"
}

export DOTFILES_DIR DRY_RUN
