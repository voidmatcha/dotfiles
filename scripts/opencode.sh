#!/bin/bash
set -euo pipefail
TAG="opencode"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── Verify opencode is installed ──
if ! command -v opencode &>/dev/null; then
  warn "opencode not found in PATH"
  warn "Run 'brew bundle --file=$DOTFILES_DIR/Brewfile' first."
  exit 1
fi

OPENCODE_VERSION=$(opencode --version 2>/dev/null || echo "unknown")
info "Found opencode ${OPENCODE_VERSION}"

# ── Symlink global config files ──
OPENCODE_CONFIG_DIR="$HOME/.config/opencode"
mkdir -p "$OPENCODE_CONFIG_DIR"

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
  echo "On first run, opencode needs provider credentials (Anthropic, OpenAI, etc.)."
  echo "We'll launch 'opencode auth login' now — pick a provider and follow the prompts."
  echo "Press Ctrl-C to skip."
  echo ""

  if $DRY_RUN; then
    info "[dry-run] would run: opencode auth login"
  else
    read -rp "Run 'opencode auth login' now? (Y/n) " run_auth
    if [[ "$run_auth" =~ ^[Nn]$ ]]; then
      warn "Skipped. Run 'opencode auth login' manually before first use."
    else
      opencode auth login || warn "auth login exited non-zero — re-run manually if needed"
    fi
  fi
fi

info "opencode setup done"
warn "Plugins listed in opencode.json auto-install on first invocation (Bun cache)."
