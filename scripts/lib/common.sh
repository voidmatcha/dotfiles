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
NON_INTERACTIVE="${NON_INTERACTIVE:-false}"
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

# ensure_dir <path> [path...]
# Creates directories, or only reports them in dry-run mode.
ensure_dir() {
  local dir
  for dir in "$@"; do
    if $DRY_RUN; then
      info "[dry-run] mkdir -p $dir"
    else
      mkdir -p "$dir"
    fi
  done
}

next_backup_path() {
  local dst="$1"
  local candidate="${dst}.backup"
  local index=1

  while [ -e "$candidate" ] || [ -L "$candidate" ]; do
    candidate="${dst}.backup.${index}"
    index=$((index + 1))
  done

  printf '%s\n' "$candidate"
}

# link_file "<source>" "<destination>"
# Backs up an existing real file (not symlink) before linking. Honors DRY_RUN.
link_file() {
  local src="$1"
  local dst="$2"
  local backup_dst

  if $DRY_RUN; then
    info "[dry-run] ln -sf $src -> $dst"
    return 0
  fi

  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    backup_dst="$(next_backup_path "$dst")"
    warn "Backing up $dst -> $backup_dst"
    mv "$dst" "$backup_dst"
  fi

  if [ -L "$dst" ]; then
    rm "$dst"
  fi

  mkdir -p "$(dirname "$dst")"
  ln -sf "$src" "$dst"
  info "Linked: $src -> $dst"
}

# with_timeout <secs> <cmd> [args...]
# macOS has no `timeout`; perl's alarm sends SIGALRM after N seconds (exit 142).
# Use to bound third-party CLIs that may hang on first-run downloads, network
# stalls, or unexpected interactive prompts — without blocking install.sh.
with_timeout() {
  local secs="$1"; shift
  perl -e 'alarm shift; exec @ARGV' "$secs" "$@"
}

# json_entry_exists <file> <jq-filter> [extra jq args, e.g. --arg n "val"]
# Used to skip already-applied idempotent operations whose CLI hangs on re-apply.
# Pass shell-controlled values via `--arg` to avoid jq filter injection.
json_entry_exists() {
  local file="$1" filter="$2"; shift 2
  [ -f "$file" ] || return 1
  command -v jq &>/dev/null || return 1
  jq -e "$@" "$filter" "$file" >/dev/null 2>&1
}

export DOTFILES_DIR DRY_RUN NON_INTERACTIVE
