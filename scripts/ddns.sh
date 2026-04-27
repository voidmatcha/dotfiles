#!/bin/bash
set -euo pipefail

DOTFILES_DIR="${DOTFILES_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
DRY_RUN="${DRY_RUN:-false}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info() { echo -e "${GREEN}[ddns]${NC} $1"; }
warn() { echo -e "${YELLOW}[ddns]${NC} $1"; }

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.user.duckdns.plist"
PLIST_DST="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo ""
echo "=== DuckDNS setup ==="
echo ""
echo "Go to https://www.duckdns.org, sign in, and create a subdomain."
echo ""

# Read existing values from installed plist if present
_cur_domain=""
_cur_token=""
if [ -f "$PLIST_DST" ]; then
  _cur_domain=$(sed -n 's/.*domains=\([^&]*\).*/\1/p' "$PLIST_DST" 2>/dev/null | head -1 || true)
  _cur_token=$(sed -n 's/.*token=\([^&]*\).*/\1/p' "$PLIST_DST" 2>/dev/null | head -1 || true)
fi

read -rp "DuckDNS subdomain (without .duckdns.org) [${_cur_domain}]: " DUCKDNS_DOMAIN
DUCKDNS_DOMAIN="${DUCKDNS_DOMAIN:-$_cur_domain}"

read -rp "DuckDNS token [${_cur_token:+****${_cur_token: -4}}]: " DUCKDNS_TOKEN
DUCKDNS_TOKEN="${DUCKDNS_TOKEN:-$_cur_token}"

if [ -z "$DUCKDNS_DOMAIN" ] || [ -z "$DUCKDNS_TOKEN" ]; then
  warn "Domain and token are required. Skipping DuckDNS setup."
  exit 0
fi

# ── Test the API ──
info "Testing DuckDNS update..."
if $DRY_RUN; then
  info "[dry-run] curl DuckDNS update API"
else
  RESULT=$(curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=")
  if [ "$RESULT" = "OK" ]; then
    info "DuckDNS update successful: ${DUCKDNS_DOMAIN}.duckdns.org"
  else
    warn "DuckDNS returned: $RESULT — check your domain/token"
    exit 1
  fi
fi

# ── Install LaunchAgent ──
info "Installing DuckDNS LaunchAgent (updates every 5 min)..."
if $DRY_RUN; then
  info "[dry-run] Install plist → $PLIST_DST"
else
  mkdir -p "$LAUNCH_AGENTS_DIR"

  # Unload old agent if running
  launchctl unload "$PLIST_DST" 2>/dev/null || true

  # Generate plist from template
  sed -e "s/__DUCKDNS_DOMAIN__/${DUCKDNS_DOMAIN}/g" \
      -e "s/__DUCKDNS_TOKEN__/${DUCKDNS_TOKEN}/g" \
      "$DOTFILES_DIR/configs/com.user.duckdns.plist" > "$PLIST_DST"

  launchctl load "$PLIST_DST"
  info "LaunchAgent loaded: updates ${DUCKDNS_DOMAIN}.duckdns.org every 5 min"
fi

echo ""
info "DuckDNS setup done"
info "Your hostname: ${DUCKDNS_DOMAIN}.duckdns.org"
warn "To check: cat /tmp/duckdns.log"
