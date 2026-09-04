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

# render_file <src> <dst>
# copy_file, but expanding __HOME__ first. launchd does not expand variables in
# a plist, so a LaunchAgent that must write under the user's home has to be
# rendered at install time rather than copied.
render_file() {
  local src="$1"
  local dst="$2"

  if $DRY_RUN; then
    info "[dry-run] render $src -> $dst"
    return 0
  fi

  mkdir -p "$(dirname "$dst")"
  local tmp
  tmp="$(mktemp)"
  sed -e "s|__HOME__|$HOME|g" "$src" > "$tmp"
  if [ -f "$dst" ] && cmp -s "$tmp" "$dst"; then
    rm -f "$tmp"
    return 0
  fi
  mv "$tmp" "$dst"
  chmod 0644 "$dst"
  info "Rendered: $src -> $dst"
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

# run_sdkman <sdk args...>
# Current SDKMAN releases contain shell-specific parameter expansion. Sourcing
# them into macOS' Bash 3.2 can fail before `sdk` runs, while the configured
# interactive shell is zsh. Keep SDKMAN in a zsh subprocess and let its on-disk
# candidate symlinks carry the result back to later shells.
run_sdkman() {
  if ! command -v zsh >/dev/null 2>&1; then
    warn "zsh not found — cannot run SDKMAN safely"
    return 1
  fi
  if [ ! -s "$HOME/.sdkman/bin/sdkman-init.sh" ]; then
    warn "SDKMAN init script not found"
    return 1
  fi

  SDKMAN_DIR="$HOME/.sdkman" zsh -c '
    source "$SDKMAN_DIR/bin/sdkman-init.sh"
    sdk "$@"
  ' dotfiles-sdkman "$@"
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

# ensure_npm_global_latest <package> <cli>
# Install a missing global CLI, or ask npm to converge it to the registry's
# latest release during an explicit --upgrade run. npm itself performs the
# version comparison, so an already-current package remains a cheap no-op.
ensure_npm_global_latest() {
  local package="$1"
  local cli="$2"

  if $DRY_RUN; then
    if $UPGRADE; then
      info "[dry-run] npm install -g ${package}@latest"
    else
      info "[dry-run] npm install -g ${package}@latest (if $cli is missing)"
    fi
    return 0
  fi

  if command -v "$cli" >/dev/null 2>&1 && ! $UPGRADE; then
    info "$cli already installed"
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    warn "npm not found — cannot install or update $package"
    return 1
  fi

  if command -v "$cli" >/dev/null 2>&1; then
    info "Ensuring $cli is at the latest release..."
  else
    info "Installing $cli (global)..."
  fi
  npm install -g "${package}@latest"
}

# ensure_pipx_latest <package> <cli>
# pipx has a native upgrade operation and preserves the existing environment
# when the installed release is already current.
ensure_pipx_latest() {
  local package="$1"
  local cli="$2"

  if $DRY_RUN; then
    if $UPGRADE; then
      info "[dry-run] pipx upgrade $package"
    else
      info "[dry-run] pipx install $package (if $cli is missing)"
    fi
    return 0
  fi

  if ! command -v pipx >/dev/null 2>&1; then
    warn "pipx not found — cannot install or update $package"
    return 1
  fi
  if command -v "$cli" >/dev/null 2>&1; then
    if $UPGRADE; then
      info "Ensuring $cli is at the latest release..."
      pipx upgrade "$package"
    else
      info "$cli already installed"
    fi
  else
    info "Installing $cli via pipx..."
    pipx install "$package"
  fi
}

# ensure_github_release_binary_latest <repo> <asset> <destination> <name>
# Refresh a directly downloaded GitHub release binary only when the latest tag
# differs. The candidate is downloaded and version-checked beside the existing
# binary before an atomic rename, so a network or asset failure keeps the last
# working version intact.
ensure_github_release_binary_latest() {
  local repo="$1"
  local asset="$2"
  local destination="$3"
  local name="$4"
  local metadata latest_tag latest_version latest_url current_output current_version
  local candidate candidate_output candidate_version

  if [ -x "$destination" ] && ! $UPGRADE; then
    info "$name already installed"
    return 0
  fi
  if $DRY_RUN; then
    if [ -x "$destination" ]; then
      info "[dry-run] check $repo latest release and update $destination if newer"
    else
      info "[dry-run] install $repo latest release to $destination"
    fi
    return 0
  fi
  if ! command -v jq >/dev/null 2>&1; then
    warn "$name: jq is required to resolve GitHub release metadata"
    return 1
  fi

  if ! metadata="$(curl -fsSL "https://api.github.com/repos/${repo}/releases/latest")"; then
    warn "$name: failed to query the latest GitHub release"
    return 1
  fi
  latest_tag="$(printf '%s' "$metadata" | jq -r '.tag_name // empty')"
  latest_version="${latest_tag#v}"
  latest_url="$(printf '%s' "$metadata" | jq -r --arg asset "$asset" \
    '.assets[]? | select(.name == $asset) | .browser_download_url' | head -1)"
  if [ -z "$latest_tag" ] || [ -z "$latest_url" ] || [ "$latest_url" = "null" ]; then
    warn "$name: latest release does not contain asset $asset"
    return 1
  fi

  if [ -x "$destination" ]; then
    current_output="$("$destination" --version 2>/dev/null || true)"
    current_version="$(printf '%s' "$current_output" | grep -Eo '[0-9]+(\.[0-9]+)+' | head -1 || true)"
    if [ -n "$current_version" ] && [ "$current_version" = "$latest_version" ]; then
      info "$name is already latest ($latest_tag)"
      return 0
    fi
  fi

  mkdir -p "$(dirname "$destination")"
  candidate="$(mktemp "${destination}.tmp.XXXXXX")"
  if ! curl -fsSL "$latest_url" -o "$candidate"; then
    rm -f "$candidate"
    warn "$name: download failed from $latest_url; keeping the installed version"
    return 1
  fi
  chmod +x "$candidate"
  candidate_output="$("$candidate" --version 2>/dev/null || true)"
  candidate_version="$(printf '%s' "$candidate_output" | grep -Eo '[0-9]+(\.[0-9]+)+' | head -1 || true)"
  if [ -z "$candidate_version" ] || [ "$candidate_version" != "$latest_version" ]; then
    rm -f "$candidate"
    warn "$name: downloaded asset failed version validation; keeping the installed version"
    return 1
  fi

  mv -f "$candidate" "$destination"
  info "$name updated to $latest_tag"
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

# ~/.codex/AGENTS.md is composed from two tracked sources rather than symlinked,
# because Codex has no import mechanism and the shared half must not replace the
# Codex-only contract. Both the writer (codex.sh) and the checker (doctor.sh)
# need the exact same bytes, so the recipe lives here: a marker that drifts
# between the two would make doctor report every machine as unmanaged.
CODEX_AGENTS_MARKER="GENERATED by scripts/codex.sh"

codex_agents_sources_ok() {
  [ -f "$DOTFILES_DIR/configs/codex/AGENTS.md" ] &&
    [ -f "$DOTFILES_DIR/configs/AGENTS.md" ]
}

# Writes the composite to stdout. Callers redirect it where they need it.
codex_agents_compose() {
  printf '<!-- %s. Do not edit this file directly.\n' "$CODEX_AGENTS_MARKER"
  printf '     Codex-only part: configs/codex/AGENTS.md\n'
  printf '     Shared part:     configs/AGENTS.md (also used by Claude) -->\n\n'
  cat "$DOTFILES_DIR/configs/codex/AGENTS.md"
  printf '\n---\n\n'
  cat "$DOTFILES_DIR/configs/AGENTS.md"
}

# The marker is written on the first line. Grepping the whole file would also
# match a hand-written note that merely mentions the marker, and that file would
# then be overwritten with no backup.
codex_agents_is_managed() {
  [ -f "$1" ] && head -1 "$1" | grep -q "$CODEX_AGENTS_MARKER"
}

export DOTFILES_DIR DRY_RUN NON_INTERACTIVE UPGRADE CODEX_AGENTS_MARKER
