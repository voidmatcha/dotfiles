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
    agent-worktrees
    agent-worktrees-cmux
    agent-worktree-url
    agent-worktree-link
    agent-worktree-cmux
  )
  if $DRY_RUN; then
    for name in "${helpers[@]}"; do
      case "$name" in
        agent-worktrees|agent-worktrees-cmux|agent-worktree-url|agent-worktree-link|agent-worktree-cmux)
          src="$DOTFILES_DIR/scripts/worktree-workspace.sh"
          ;;
        *)
          src="$DOTFILES_DIR/scripts/${name}.sh"
          ;;
      esac
      info "[dry-run] ln -sf $src -> $STATUSLINE_BIN_DIR/$name"
    done
    return 0
  fi

  ensure_dir "$STATUSLINE_BIN_DIR"
  for name in "${helpers[@]}"; do
    case "$name" in
      agent-worktrees|agent-worktrees-cmux|agent-worktree-url|agent-worktree-link|agent-worktree-cmux)
        src="$DOTFILES_DIR/scripts/worktree-workspace.sh"
        ;;
      *)
        src="$DOTFILES_DIR/scripts/${name}.sh"
        ;;
    esac
    chmod +x "$src"
    ln -sf "$src" "$STATUSLINE_BIN_DIR/$name"
    info "Installed statusline helper: $STATUSLINE_BIN_DIR/$name"
  done
}

install_statusline_helpers
info "Agent statusline/worktree helpers installed"
