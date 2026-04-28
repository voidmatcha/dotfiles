#!/bin/bash
set -euo pipefail
TAG="shell"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

ZSH_CUSTOM="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}"

# ── Oh My Zsh ──
if [ -d "$HOME/.oh-my-zsh" ]; then
  info "Oh My Zsh already installed"
else
  info "Installing Oh My Zsh..."
  if $DRY_RUN; then
    info "[dry-run] Skipping Oh My Zsh install"
  else
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
  fi
fi

# ── Plugins ──
install_plugin() {
  local name="$1"
  local repo="$2"
  local dest="$ZSH_CUSTOM/plugins/$name"

  if [ -d "$dest" ]; then
    info "$name already installed"
    return
  fi

  info "Installing $name..."
  if $DRY_RUN; then
    info "[dry-run] Skipping $name install"
  else
    git clone --depth=1 "$repo" "$dest"
  fi
}

install_plugin "zsh-autosuggestions" "https://github.com/zsh-users/zsh-autosuggestions.git"
install_plugin "zsh-syntax-highlighting" "https://github.com/zsh-users/zsh-syntax-highlighting.git"
install_plugin "zsh-completions" "https://github.com/zsh-users/zsh-completions.git"

info "Shell setup done"
