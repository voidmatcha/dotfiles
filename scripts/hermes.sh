#!/bin/bash
set -euo pipefail
TAG="hermes"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# Hermes Agent (Nous Research) — self-improving AI agent.
# Plain upstream install; the installer handles platform-specific setup.
# https://github.com/NousResearch/hermes-agent
INSTALLER_URL="https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh"

if $DRY_RUN; then
  if command -v hermes >/dev/null 2>&1; then
    info "[dry-run] hermes already installed — would skip"
  else
    info "[dry-run] curl -fsSL $INSTALLER_URL | bash"
  fi
  exit 0
fi

if command -v hermes >/dev/null 2>&1; then
  info "hermes already installed ($(hermes --version 2>/dev/null || echo unknown)) — skipping"
  exit 0
fi

info "Installing Hermes Agent via upstream installer..."
curl -fsSL "$INSTALLER_URL" | bash

info "hermes setup done"
warn "Reload your shell (source ~/.zshrc) then run 'hermes setup' to configure model + integrations."
