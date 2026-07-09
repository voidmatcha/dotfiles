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
# upgrade. Independent refresh/install failures are collected so all safe steps
# run, but the final status remains non-zero when any requested step failed.

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

failure_count=0
failure_summary=""
checkout_refresh_failed=0
skip_company_overlay="${SKIP_COMPANY_OVERLAY:-false}"
canonical_dotfiles_dir=""
checkout_root=""
checkout_status=""

record_failure() {
  local label="$1"
  failure_count=$((failure_count + 1))
  if [ -n "$failure_summary" ]; then
    failure_summary="$failure_summary, $label"
  else
    failure_summary="$label"
  fi
  warn "$label failed (continuing to collect remaining results)"
}

# 1) prove the checkout identity before running any code from it, then refresh
# it when requested (symlinked configs then go live immediately).
if ! command -v git &>/dev/null; then
  record_failure "git checkout validation"
  checkout_refresh_failed=1
elif ! canonical_dotfiles_dir="$(cd "$DOTFILES_DIR" 2>/dev/null && pwd -P)"; then
  warn "cannot resolve dotfiles checkout path: $DOTFILES_DIR"
  record_failure "git checkout validation"
  checkout_refresh_failed=1
elif ! checkout_root="$(git -C "$DOTFILES_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  warn "dotfiles path is not a valid git checkout: $DOTFILES_DIR"
  record_failure "git checkout validation"
  checkout_refresh_failed=1
elif [ "$checkout_root" != "$canonical_dotfiles_dir" ]; then
  warn "dotfiles checkout root mismatch (expected $canonical_dotfiles_dir, git reports $checkout_root)"
  record_failure "git checkout validation"
  checkout_refresh_failed=1
elif ! $DO_PULL; then
  info "git pull: skipped (--no-pull)"
elif ! checkout_status="$(git -C "$DOTFILES_DIR" status --porcelain 2>/dev/null)"; then
  record_failure "git checkout status"
  checkout_refresh_failed=1
elif [ -n "$checkout_status" ]; then
  record_failure "git pull (dirty checkout)"
  checkout_refresh_failed=1
elif $APPLY; then
  info "git pull --ff-only (latest dotfiles)"
  if git -C "$DOTFILES_DIR" pull --ff-only; then
    info "git pull succeeded"
  else
    record_failure "git pull"
    checkout_refresh_failed=1
  fi

  # Pulling the parent can change submodule pins. Refresh them before install
  # so the company overlay is never run from a checkout older than the parent.
  if [ "$checkout_refresh_failed" -eq 0 ]; then
    info "git submodule update --init --recursive"
    if git -C "$DOTFILES_DIR" submodule update --init --recursive; then
      info "git submodule update succeeded"
    else
      record_failure "git submodule update"
      skip_company_overlay="true"
    fi
  else
    warn "skipping submodule refresh because the parent checkout did not update safely"
  fi
else
  info "[check] would: git -C $DOTFILES_DIR pull --ff-only"
  info "[check] would: git -C $DOTFILES_DIR submodule update --init --recursive"
fi

# 2) full idempotent setup + per-tool version upgrades
if [ "$checkout_refresh_failed" -ne 0 ]; then
  warn "skipping install.sh because the requested checkout refresh did not complete safely"
elif $APPLY; then
  info "install.sh --non-interactive --upgrade (setup + version upgrades; skips what's current)"
  if SKIP_COMPANY_OVERLAY="$skip_company_overlay" \
      bash "$DOTFILES_DIR/install.sh" --non-interactive --upgrade; then
    info "install.sh --upgrade succeeded"
  else
    record_failure "install.sh --upgrade"
  fi
else
  info "install.sh --dry-run --upgrade (preview — no changes)"
  if ! bash "$DOTFILES_DIR/install.sh" --dry-run --upgrade; then
    record_failure "install.sh --dry-run --upgrade"
  fi
fi

if [ "$failure_count" -gt 0 ]; then
  warn "completed with $failure_count failure(s): $failure_summary"
  exit 1
fi

info "done (all requested update steps completed successfully)"
