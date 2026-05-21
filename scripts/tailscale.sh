#!/bin/bash
set -euo pipefail
TAG="tailscale"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── Check Tailscale is installed ──
if ! [ -d "/Applications/Tailscale.app" ]; then
  if $DRY_RUN; then
    warn "[dry-run] Tailscale.app not found at /Applications/Tailscale.app"
    warn "[dry-run] real setup requires Brewfile install first."
  else
    error "Tailscale.app not found at /Applications/Tailscale.app"
    error "Run 'brew bundle --file=$DOTFILES_DIR/Brewfile' first, then re-run this script."
    exit 1
  fi
fi

# CLI is bundled inside the app on macOS
TAILSCALE_CLI="/Applications/Tailscale.app/Contents/MacOS/Tailscale"

# ── Symlink CLI into PATH ──
if ! command -v tailscale &>/dev/null; then
  info "Linking Tailscale CLI into ~/.local/bin..."
  if $DRY_RUN; then
    info "[dry-run] ln -sf $TAILSCALE_CLI ~/.local/bin/tailscale"
  else
    ensure_dir "$HOME/.local/bin"
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
echo "  - Tailscale SSH for shell access — no port forwarding, no separate keys"
echo "  - Network is private — invisible to the internet"
echo ""

if $DRY_RUN; then
  info "[dry-run] Skipping Tailscale status check"
  info "[dry-run] tailscale set --ssh"
else
  if $NON_INTERACTIVE; then
    warn "Non-interactive mode: checking current Tailscale status without waiting for sign-in."
  else
    read -rp "Press Enter once you've signed in to Tailscale..."
  fi

  if "$TAILSCALE_CLI" status &>/dev/null; then
    info "Tailscale connected"
    echo ""
    "$TAILSCALE_CLI" status
    echo ""
    info "Your hostname: $("$TAILSCALE_CLI" status --json 2>/dev/null | grep -o '"DNSName":"[^"]*"' | head -1 | cut -d'"' -f4 || echo 'check Tailscale app')"

    # Enable Tailscale SSH — replaces OpenSSH for inbound shell access. Identity
    # comes from the tailnet (no password, no separate ssh keys, no TOTP), and
    # access is gated by Tailscale ACLs in the admin console.
    info "Enabling Tailscale SSH..."
    if "$TAILSCALE_CLI" set --ssh; then
      info "Tailscale SSH enabled — connect with: tailscale ssh $(whoami)@<hostname>"
    else
      warn "tailscale set --ssh failed — enable it manually in the admin console"
    fi
  else
    warn "Tailscale not connected — sign in via the menu bar app, then re-run this script"
  fi
fi

echo ""
info "Tailscale setup done"
warn "Remember: install Tailscale on your phone too (App Store / Play Store)"
warn "OpenSSH Remote Login is intentionally left available as a fallback by macos.sh."
warn "If you only want Tailscale SSH, turn it off manually:"
warn "  System Settings → General → Sharing → Remote Login"
