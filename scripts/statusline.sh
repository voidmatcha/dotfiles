#!/bin/bash
set -euo pipefail
TAG="statusline"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

STATUSLINE_BIN_DIR="$HOME/.local/bin"

install_statusline_helpers() {
  local name src
  local helpers=(
    agent-session-label
    claude-statusline
  )
  if $DRY_RUN; then
    for name in "${helpers[@]}"; do
      src="$DOTFILES_DIR/scripts/${name}.sh"
      info "[dry-run] ln -sf $src -> $STATUSLINE_BIN_DIR/$name"
    done
    return 0
  fi

  ensure_dir "$STATUSLINE_BIN_DIR"
  for name in "${helpers[@]}"; do
    src="$DOTFILES_DIR/scripts/${name}.sh"
    chmod +x "$src"
    ln -sf "$src" "$STATUSLINE_BIN_DIR/$name"
    info "Installed statusline helper: $STATUSLINE_BIN_DIR/$name"
  done
}

install_statusline_helpers
info "Agent statusline helpers installed"
