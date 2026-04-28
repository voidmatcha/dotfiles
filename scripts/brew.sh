#!/bin/bash
set -euo pipefail
TAG="brew"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# Install Homebrew
if ! command -v brew &>/dev/null; then
  info "Installing Homebrew..."
  if $DRY_RUN; then
    info "[dry-run] Skipping Homebrew install"
  else
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Set up path for Apple Silicon
    if [[ "$(uname -m)" == "arm64" ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
  fi
else
  info "Homebrew already installed"
fi

# Run Brewfile
info "Installing packages from Brewfile..."
if $DRY_RUN; then
  info "[dry-run] Skipping brew bundle"
  info "[dry-run] Packages that would be installed:"
  cat "$DOTFILES_DIR/Brewfile"
else
  brew update
  brew bundle --file="$DOTFILES_DIR/Brewfile"
fi

info "Homebrew setup done"
