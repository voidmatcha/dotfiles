#!/bin/bash
set -euo pipefail
TAG="tailscale"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── Check Tailscale is installed ──
if ! [ -d "/Applications/Tailscale.app" ]; then
  error "Tailscale.app not found at /Applications/Tailscale.app"
  error "Run 'brew bundle --file=$DOTFILES_DIR/Brewfile' first, then re-run this script."
  exit 1
fi

# CLI is bundled inside the app on macOS
TAILSCALE_CLI="/Applications/Tailscale.app/Contents/MacOS/Tailscale"

# ── Symlink CLI into PATH ──
if ! command -v tailscale &>/dev/null; then
  info "Linking Tailscale CLI into ~/.local/bin..."
  if $DRY_RUN; then
    info "[dry-run] ln -sf $TAILSCALE_CLI ~/.local/bin/tailscale"
  else
    mkdir -p "$HOME/.local/bin"
    ln -sf "$TAILSCALE_CLI" "$HOME/.local/bin/tailscale"
    info "Linked: tailscale → $TAILSCALE_CLI"
  fi
fi

# ── Check login status ──
echo ""
echo "=== Tailscale setup ==="
echo ""
echo "Open the Tailscale app (in menu bar) and sign in to your account."
echo "Free tier: unlimited devices, up to 6 users."
echo ""
echo "After signing in:"
echo "  - Each device gets a 100.x.x.x IP and a *.ts.net hostname"
echo "  - SSH/mosh access via that IP, no port forwarding needed"
echo "  - Network is private — invisible to the internet"
echo ""

if $DRY_RUN; then
  info "[dry-run] Skipping Tailscale status check"
else
  read -rp "Press Enter once you've signed in to Tailscale..."

  if "$TAILSCALE_CLI" status &>/dev/null; then
    info "Tailscale connected"
    echo ""
    "$TAILSCALE_CLI" status
    echo ""
    info "Your hostname: $("$TAILSCALE_CLI" status --json 2>/dev/null | grep -o '"DNSName":"[^"]*"' | head -1 | cut -d'"' -f4 || echo 'check Tailscale app')"
  else
    warn "Tailscale not connected — sign in via the menu bar app"
  fi
fi

echo ""
info "Tailscale setup done"
warn "Remember: install Tailscale on your phone too (App Store / Play Store)"
warn "After everything works, you can close router port 22 forwarding"
