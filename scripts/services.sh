#!/bin/bash
set -euo pipefail
TAG="services"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# Installs LaunchAgents for purplemux and code-server. Each runs at login and
# is auto-restarted (KeepAlive=true). code-server binds to 127.0.0.1 (kernel-
# level isolation). purplemux binds to *:8022 (no --bind flag upstream) but
# enforces `networkAccess: "tailscale"` at the app layer — non-tailnet/non-
# loopback IPs get HTTP 403 before auth. Both are exposed via `tailscale serve`
# so the public-facing transport is HTTPS over the tailnet (cert from Tailscale,
# not from the app).

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

install_agent() {
  local label="$1"
  local plist_src="$2"
  local wrapper_src="$3"
  local wrapper_dst
  wrapper_dst="$HOME/.local/bin/$(basename "$wrapper_src")"
  local plist_dst="$LAUNCH_AGENTS_DIR/${label}.plist"

  if $DRY_RUN; then
    info "[dry-run] would install wrapper to $wrapper_dst and load $label"
    return 0
  fi

  mkdir -p "$LAUNCH_AGENTS_DIR" "$HOME/Library/Logs" "$HOME/.local/bin"
  install -m 755 "$wrapper_src" "$wrapper_dst"
  sed -e "s|__WRAPPER_PATH__|$wrapper_dst|g" \
      -e "s|__HOME__|$HOME|g" \
      "$plist_src" > "$plist_dst"
  launchctl unload "$plist_dst" 2>/dev/null || true
  launchctl load "$plist_dst"
  info "LaunchAgent installed: $label"
}

# ── purplemux: ensure global npm install ──
if command -v purplemux >/dev/null 2>&1; then
  info "Found purplemux ($(purplemux --version 2>/dev/null || echo unknown))"
elif command -v npm >/dev/null 2>&1; then
  if $DRY_RUN; then
    info "[dry-run] would run: npm install -g purplemux"
  else
    info "Installing purplemux via npm..."
    npm install -g purplemux
  fi
else
  warn "npm not found — install Node first (scripts/dev.sh), then run this script again."
fi

install_agent "com.user.purplemux" \
              "$DOTFILES_DIR/configs/com.user.purplemux.plist" \
              "$DOTFILES_DIR/scripts/purplemux-launch.sh"

# ── code-server: brew-managed, scaffold config if missing ──
if ! command -v code-server >/dev/null 2>&1; then
  warn "code-server not in PATH. Run 'brew bundle --file=$DOTFILES_DIR/Brewfile' first."
fi

CODE_SERVER_CONFIG="$HOME/.config/code-server/config.yaml"
if [ ! -f "$CODE_SERVER_CONFIG" ]; then
  if $DRY_RUN; then
    info "[dry-run] would scaffold $CODE_SERVER_CONFIG"
  else
    mkdir -p "$(dirname "$CODE_SERVER_CONFIG")"
    # Generate a random password so the default install is not unauthenticated.
    pw=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)
    cat > "$CODE_SERVER_CONFIG" <<EOF
bind-addr: 127.0.0.1:8088
auth: password
password: $pw
cert: false
EOF
    warn "Scaffolded $CODE_SERVER_CONFIG with a random password."
    warn "View it with: cat $CODE_SERVER_CONFIG"
  fi
fi

# Always lock the password file down — the chmod inside the scaffold branch
# only runs on a fresh install. Pre-existing files (e.g. from a prior
# code-server install that defaulted to 0644) need this.
if [ -f "$CODE_SERVER_CONFIG" ] && ! $DRY_RUN; then
  chmod 600 "$CODE_SERVER_CONFIG"
fi

install_agent "com.user.code-server" \
              "$DOTFILES_DIR/configs/com.user.code-server.plist" \
              "$DOTFILES_DIR/scripts/code-server-launch.sh"

info "services setup done"
warn "Expose to your tailnet (HTTPS via the tailnet cert; no plaintext on LAN):"
warn "  tailscale serve --bg --https=443 --set-path=/ http://localhost:8022   # purplemux"
warn "  tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088  # code-server"
warn "Then restrict by Tailscale ACL — both endpoints are inside the tailnet only."
