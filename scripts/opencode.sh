#!/bin/bash
set -euo pipefail
TAG="opencode"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── Verify opencode is installed ──
if $DRY_RUN; then
  if command -v opencode &>/dev/null; then
    info "[dry-run] opencode present — would check version"
  else
    warn "[dry-run] opencode not found in PATH; real setup requires Brewfile install first."
  fi
elif command -v opencode &>/dev/null; then
  OPENCODE_VERSION=$(opencode --version 2>/dev/null || echo "unknown")
  info "Found opencode ${OPENCODE_VERSION}"
else
  warn "opencode not found in PATH"
  warn "Run 'brew bundle --file=$DOTFILES_DIR/Brewfile' first."
  exit 1
fi

# ── Symlink global config files ──
OPENCODE_CONFIG_DIR="$HOME/.config/opencode"
ensure_dir "$OPENCODE_CONFIG_DIR"

link_file "$DOTFILES_DIR/configs/opencode/opencode.json" \
          "$OPENCODE_CONFIG_DIR/opencode.json"
link_file "$DOTFILES_DIR/configs/opencode/oh-my-openagent.json" \
          "$OPENCODE_CONFIG_DIR/oh-my-openagent.json"
link_file "$DOTFILES_DIR/configs/AGENTS.md" \
          "$OPENCODE_CONFIG_DIR/AGENTS.md"

# ── Auth check ──
AUTH_FILE="$HOME/.local/share/opencode/auth.json"
if [ -s "$AUTH_FILE" ]; then
  info "opencode auth already configured ($AUTH_FILE exists)"
else
  echo ""
  warn "opencode is not authenticated yet."
  echo ""
  echo "On first run, opencode needs provider credentials for OpenAI primary and Anthropic fallback models."
  echo "We'll launch 'opencode auth login' now — pick a provider and follow the prompts."
  echo "Afterwards, verify both OpenAI primary and Anthropic fallback auth are configured before relying on fallback routing."
  echo "Press Ctrl-C to skip."
  echo ""

  if $DRY_RUN; then
    info "[dry-run] would run: opencode auth login"
  else
    if $NON_INTERACTIVE; then
      warn "Non-interactive mode: skipped opencode auth login. Run it manually before first use."
    else
      read -rp "Run 'opencode auth login' now? (Y/n) " run_auth
      if [[ "$run_auth" =~ ^[Nn]$ ]]; then
        warn "Skipped. Run 'opencode auth login' manually before first use."
      else
        opencode auth login || warn "auth login exited non-zero — re-run manually if needed"
      fi
    fi
  fi
fi

info "opencode setup done"
warn "Verify OpenAI primary and Anthropic fallback auth with 'opencode auth login' before first use."
warn "npm plugins in opencode.json auto-install on first invocation (Bun cache)."
