#!/bin/bash
set -euo pipefail
TAG="headroom"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

HEADROOM_INSTALL_SPEC="${HEADROOM_INSTALL_SPEC:-headroom-ai[proxy,mcp,code]}"
HEADROOM_PYTHON="${HEADROOM_PYTHON:-3.13}"
WRAPPER_SRC="$DOTFILES_DIR/scripts/headroom-agent.sh"
WRAPPER_DIR="$HOME/.local/bin"

install_headroom_cli() {
  info "Checking headroom..."
  if $DRY_RUN; then
    info "[dry-run] uv tool install -p $HEADROOM_PYTHON '$HEADROOM_INSTALL_SPEC'"
    return 0
  fi

  if command -v headroom &>/dev/null; then
    info "headroom already installed ($(headroom --version 2>/dev/null || echo unknown))"
    return 0
  fi

  if command -v uv &>/dev/null; then
    info "Installing headroom via uv tool ($HEADROOM_INSTALL_SPEC)..."
    if uv tool install -p "$HEADROOM_PYTHON" "$HEADROOM_INSTALL_SPEC"; then
      info "headroom installed"
      return 0
    fi
    warn "uv tool install failed — trying pipx fallback"
  fi

  if command -v pipx &>/dev/null; then
    if pipx install "$HEADROOM_INSTALL_SPEC"; then
      info "headroom installed via pipx"
      return 0
    fi
    warn "pipx install failed"
  else
    warn "pipx not found"
  fi

  warn "headroom install failed — try manually: uv tool install -p $HEADROOM_PYTHON '$HEADROOM_INSTALL_SPEC'"
  return 0
}

install_headroom_wrappers() {
  local name
  if $DRY_RUN; then
    for name in headroom-agent claudeh codexh omxh; do
      info "[dry-run] ln -sf $WRAPPER_SRC -> $WRAPPER_DIR/$name"
    done
    return 0
  fi

  ensure_dir "$WRAPPER_DIR"
  chmod +x "$WRAPPER_SRC"
  for name in headroom-agent claudeh codexh omxh; do
    ln -sf "$WRAPPER_SRC" "$WRAPPER_DIR/$name"
    info "Installed wrapper: $WRAPPER_DIR/$name"
  done
}

install_headroom_cli
install_headroom_wrappers
info "Headroom wrapper setup done (claude/codex/omx route through them in zsh when available; use HEADROOM_DEFAULT=0 to bypass)"
