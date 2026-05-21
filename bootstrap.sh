#!/bin/bash
# bootstrap.sh — one-shot entry point for a fresh macOS machine.
#
#   curl -fsSL https://raw.githubusercontent.com/voidmatcha/dotfiles/main/bootstrap.sh | bash
#
# What it does:
#   1. Make sure git is available (installs Xcode Command Line Tools if missing).
#   2. Clone (or update) this repo with submodules into $DOTFILES_DIR (default ~/dotfiles).
#   3. Hand off to ./install.sh, passing any args through (e.g. --dry-run).
#
# Idempotent: safe to re-run. Pulls latest if the repo is already present.

set -euo pipefail

REPO_URL="${DOTFILES_REPO_URL:-https://github.com/voidmatcha/dotfiles.git}"
DOTFILES_DIR="${DOTFILES_DIR:-$HOME/dotfiles}"

color() { [ -t 1 ] && printf '\033[%sm%s\033[0m' "$1" "$2" || printf '%s' "$2"; }
info()  { echo "$(color '0;32' '[bootstrap]') $*"; }
warn()  { echo "$(color '1;33' '[bootstrap]') $*" >&2; }
die()   { echo "$(color '0;31' '[bootstrap]') $*" >&2; exit 1; }

# ── 1. Prerequisites ──
if [ "$(uname -s)" != "Darwin" ]; then
  die "bootstrap.sh only supports macOS (uname=$(uname -s))."
fi

if ! command -v git &>/dev/null; then
  info "git not found — installing Xcode Command Line Tools (a GUI dialog will open)."
  xcode-select --install >/dev/null 2>&1 || true
  info "Waiting for Command Line Tools to finish installing (this can take 5–10 min)..."
  until xcode-select -p &>/dev/null && command -v git &>/dev/null; do
    sleep 10
  done
  info "git is available."
fi

# ── 2. Clone or update ──
if [ -d "$DOTFILES_DIR/.git" ]; then
  info "Repo already present at $DOTFILES_DIR — pulling latest..."
  git -C "$DOTFILES_DIR" pull --ff-only || warn "fast-forward pull failed; leaving repo as-is"
  info "Updating submodules..."
  git -C "$DOTFILES_DIR" submodule update --init --recursive || \
    warn "submodule update failed (likely no auth to internal git host — install.sh will run without the company overlay)"
else
  info "Cloning $REPO_URL → $DOTFILES_DIR"
  # Clone the parent first (always succeeds for the public repo).
  git clone "$REPO_URL" "$DOTFILES_DIR"

  # The company/ submodule lives on an internal git host (see .gitmodules).
  # Probe SSH access to that host before trying submodule update so we can
  # give the user a clear setup window instead of a cryptic failure.
  if [ -f "$DOTFILES_DIR/.gitmodules" ]; then
    submodule_host=$(awk -F'[@:]' '/url = git@/{ print $2; exit }' "$DOTFILES_DIR/.gitmodules" 2>/dev/null || true)
    if [ -n "${submodule_host:-}" ]; then
      info "Probing SSH access to $submodule_host (submodule host)..."
      # Add the host key to known_hosts non-interactively so the SSH probe
      # below doesn't get blocked by a yes/no prompt.
      mkdir -p "$HOME/.ssh"
      ssh-keyscan -t ed25519,rsa "$submodule_host" >> "$HOME/.ssh/known_hosts" 2>/dev/null || true

      # `ssh -T` returns 1 on success for GitHub-style hosts (the greeting
      # message), so we accept both 0 and 1 as "authenticated". 255 == real
      # auth/network failure.
      set +e
      ssh -o BatchMode=yes -T "git@$submodule_host" >/dev/null 2>&1
      ssh_rc=$?
      set -e
      if [ $ssh_rc -eq 0 ] || [ $ssh_rc -eq 1 ]; then
        info "SSH auth OK — initializing company/ submodule"
        git -C "$DOTFILES_DIR" submodule update --init --recursive || \
          warn "submodule update unexpectedly failed; install.sh will proceed without the company overlay"
      else
        warn "SSH auth to $submodule_host failed (exit $ssh_rc)."
        warn "If this is a corporate machine, set up SSH access before continuing:"
        warn "  1) Register ~/.ssh/id_ed25519.pub on $submodule_host (Auth + Signing keys)."
        warn "  2) Verify:  ssh -T git@$submodule_host   (expect 'Hi <user>!')"
        warn ""
        if [ -t 0 ]; then
          read -rp "Press Enter when SSH is set up to retry submodule init, or 's' to skip: " resp
          if [ "${resp:-}" != "s" ] && [ "${resp:-}" != "S" ]; then
            git -C "$DOTFILES_DIR" submodule update --init --recursive 2>/dev/null || \
              warn "submodule update still failing — proceeding without company overlay (you can run it later: git -C $DOTFILES_DIR submodule update --init)"
          else
            info "Skipping company/ submodule — install.sh will proceed without the overlay"
          fi
        else
          # Non-interactive (curl | bash): can't prompt, so just skip and tell
          # the user how to enable it later.
          warn "Running non-interactively — skipping. Re-run after SSH setup:"
          warn "  git -C $DOTFILES_DIR submodule update --init"
        fi
      fi
    fi
  fi
fi

# ── 3. Hand off ──
info "Handing off to install.sh ..."
exec "$DOTFILES_DIR/install.sh" "$@"
