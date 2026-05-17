#!/bin/bash
set -euo pipefail
TAG="codex"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

info "Setting up Codex CLI..."

CODEX_CONFIG_DIR="${CODEX_HOME:-$HOME/.codex}"
ensure_dir "$CODEX_CONFIG_DIR"
link_file "$DOTFILES_DIR/configs/codex/config.toml" \
          "$CODEX_CONFIG_DIR/config.toml"

if command -v codex &>/dev/null; then
  CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
  info "Found codex ${CODEX_VERSION}"
elif $DRY_RUN; then
  info "[dry-run] npm install -g @openai/codex"
else
  if ! command -v npm &>/dev/null; then
    warn "npm not found in PATH"
    warn "Run 'bash $DOTFILES_DIR/scripts/dev.sh' first, or install Codex with Homebrew: brew install --cask codex"
    exit 1
  fi

  if npm install -g @openai/codex; then
    info "Codex CLI installed"
  else
    warn "Codex CLI install failed"
    exit 1
  fi
fi

# ── Auth check ──
if command -v codex &>/dev/null; then
  if codex login status >/dev/null 2>&1; then
    info "codex auth already configured"
  else
    echo ""
    warn "codex is not authenticated yet."
    echo ""
    echo "Run 'codex login' for ChatGPT sign-in, or pipe an API key with:"
    echo "  printenv OPENAI_API_KEY | codex login --with-api-key"
    echo "Use 'codex login --device-auth' for a headless device-code flow."
    echo ""

    if $DRY_RUN; then
      info "[dry-run] would run: codex login"
    elif $NON_INTERACTIVE; then
      warn "Non-interactive mode: skipped codex login. Run it manually before first use."
    else
      read -rp "Run 'codex login' now? (Y/n) " run_auth
      if [[ "$run_auth" =~ ^[Nn]$ ]]; then
        warn "Skipped. Run 'codex login' manually before first use."
      else
        codex login || warn "codex login exited non-zero — re-run manually if needed"
      fi
    fi
  fi
elif $DRY_RUN; then
  info "[dry-run] codex login status"
else
  warn "codex is still not available on PATH. Run 'codex login' after installing it."
fi

info "Codex CLI setup done"
