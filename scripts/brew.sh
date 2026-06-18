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
  # Tap trust is intentionally formula-scoped. Bun is installed from the
  # oven-sh tap for claude-mem hooks, and Homebrew refuses outdated checks for
  # untrusted third-party formulae when tap trust enforcement is enabled.
  if brew trust --help >/dev/null 2>&1; then
    brew trust --formula oven-sh/bun/bun || warn "Failed to trust oven-sh/bun/bun; brew may warn during outdated checks"
  fi

  brew update
  # docker formula now ships its own shell completions; a leftover
  # docker-completion keg owns etc/bash_completion.d/docker and makes
  # `brew link docker` fail mid-bundle. Remove it before bundling.
  if brew list --formula docker-completion &>/dev/null; then
    info "Removing docker-completion (conflicts with docker formula's bundled completions)"
    brew uninstall --force docker-completion
  fi
  brew bundle --file="$DOTFILES_DIR/Brewfile"
fi

info "Homebrew setup done"
