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
# Opt-in "re-run as upgrade". install.sh --upgrade exports this; each sub-script
# reads it to ALSO bump versions (brew upgrade, uv tool upgrade, pull git-cloned
# tools, …) on top of its normal install-if-missing. Default false = pure setup.
UPGRADE="${UPGRADE:-false}"
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

# launchd only. plists are kept as real files, not symlinks.
#
# Nothing guarantees the launchd scan at login follows a symlink, and that is
# the kind of assumption only a reboot can confirm. Every other LaunchAgent on
# this machine is a real file, so convention points the same way. The price is
# that the copy can go stale, which doctor's launchd-drift check watches for.
copy_file() {
  local src="$1"
  local dst="$2"

  if $DRY_RUN; then
    info "[dry-run] cp $src -> $dst"
    return 0
  fi

  if [ -L "$dst" ]; then
    rm -f "$dst"
  fi
  mkdir -p "$(dirname "$dst")"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    return 0
  fi
  cp "$src" "$dst"
  chmod 0644 "$dst"
  info "Copied: $src -> $dst"
}

# with_timeout <secs> <cmd> [args...]
# macOS has no `timeout`; perl's alarm sends SIGALRM after N seconds (exit 142).
# Use to bound third-party CLIs that may hang on first-run downloads, network
# stalls, or unexpected interactive prompts — without blocking install.sh.
# Normalize the wrapper and child to the universally supported C locale: macOS
# Perl aborts before exec when a parent exports Linux-only C.UTF-8.
with_timeout() {
  local secs="$1"; shift
  LC_ALL=C LC_CTYPE=C LANG=C perl -e 'alarm shift; exec @ARGV' "$secs" "$@"
}

# sudo_ok "<description>"
# Gate for sudo-requiring steps. Interactive runs always proceed (sudo prompts
# as usual). Non-interactive runs proceed only when sudo works without a
# password (cached credentials / NOPASSWD); otherwise the step is skipped with
# a warning instead of hanging on a prompt or dying under set -e.
sudo_ok() {
  $NON_INTERACTIVE || return 0
  sudo -n true 2>/dev/null && return 0
  warn "non-interactive: sudo requires a password — skipping: $*"
  return 1
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

# git_pull_if_clean <dir>
# Fast-forward a git checkout only when it is a clean repo — used by --upgrade to
# refresh git-cloned tools (oh-my-zsh, zsh plugins). No-op on a dirty tree, a
# non-repo, or DRY_RUN.
git_pull_if_clean() {
  local dir="$1"
  [ -d "$dir/.git" ] || return 0
  command -v git &>/dev/null || return 0
  if [ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ]; then
    warn "skip update (local changes): $dir"
    return 0
  fi
  if $DRY_RUN; then
    info "[dry-run] git -C $dir pull --ff-only"
    return 0
  fi
  git -C "$dir" pull --ff-only --quiet 2>/dev/null || warn "git pull failed: $dir"
}

# company_overlay_current [dotfiles-root]
# Proves the submodule is exactly at the parent gitlink and has no local or
# untracked changes before privileged/private overlay code is executed.
company_overlay_current() {
  local root="${1:-$DOTFILES_DIR}" overlay expected actual top dirty
  overlay="$root/company"
  command -v git >/dev/null 2>&1 || return 1
  [ -d "$overlay" ] && [ ! -L "$overlay" ] || return 1
  git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 1
  expected="$(git -C "$root" ls-tree HEAD -- company 2>/dev/null | awk '$1 == "160000" && $2 == "commit" { print $3; exit }')"
  actual="$(git -C "$overlay" rev-parse HEAD 2>/dev/null || true)"
  [ -n "$expected" ] && [ "$actual" = "$expected" ] || return 1
  top="$(git -C "$overlay" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ "$(cd "$overlay" && pwd -P)" = "$(cd "$top" && pwd -P)" ] || return 1
  dirty="$(git -C "$overlay" status --porcelain --untracked-files=normal 2>/dev/null)" || return 1
  [ -z "$dirty" ]
}

export DOTFILES_DIR DRY_RUN NON_INTERACTIVE UPGRADE
