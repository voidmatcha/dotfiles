#!/bin/bash
set -euo pipefail
TAG="services"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# Installs LaunchAgents for purplemux and code-server, but skips loading LaunchAgents when dependencies are missing.
# Each installed service runs at
# login and is auto-restarted (KeepAlive=true). code-server binds to 127.0.0.1 (kernel-
# level isolation). purplemux binds to *:8022 (no --bind flag upstream), so this
# repo relies on Tailscale Serve plus the macOS firewall rather than an app-level
# tailnet filter. Both are exposed via `tailscale serve` so the public-facing
# transport is HTTPS over the tailnet (cert from Tailscale, not from the app).

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

# Same ownership guard as in macos.sh (kept here too since services.sh can be
# run standalone). See macos.sh for the rationale.
if [ -d "$LAUNCH_AGENTS_DIR" ] && [ ! -w "$LAUNCH_AGENTS_DIR" ]; then
  if $DRY_RUN; then
    info "[dry-run] sudo chown -R $(whoami):staff $LAUNCH_AGENTS_DIR"
  elif sudo_ok "chown $LAUNCH_AGENTS_DIR"; then
    warn "$LAUNCH_AGENTS_DIR is not writable — fixing ownership (sudo)"
    sudo chown -R "$(whoami):$(id -gn)" "$LAUNCH_AGENTS_DIR"
  fi
fi

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
  if ! plutil -lint "$plist_dst" >/dev/null; then
    warn "Rendered LaunchAgent plist is invalid: $plist_dst"
    return 0
  fi

  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  local bootstrap_output
  if ! bootstrap_output=$(launchctl bootstrap "gui/$(id -u)" "$plist_dst" 2>&1); then
    # bootout returns before launchd finishes tearing the service down; an
    # immediate bootstrap can race it and fail with "5: Input/output error".
    # One delayed retry clears it.
    sleep 2
    if ! bootstrap_output=$(launchctl bootstrap "gui/$(id -u)" "$plist_dst" 2>&1); then
      warn "LaunchAgent bootstrap failed for $label; leaving plist installed but continuing."
      while IFS= read -r line; do
        [ -n "$line" ] && warn "  $line"
      done <<< "$bootstrap_output"
      warn "Debug manually with: launchctl bootstrap gui/$(id -u) $plist_dst"
      warn "Then check logs: tail -n 80 $HOME/Library/Logs/${label#com.user.}.err.log"
      return 0
    fi
  fi

  info "LaunchAgent installed: $label"
}

# ── purplemux: ensure global npm install ──
purplemux_ready=false
if $DRY_RUN; then
  info "[dry-run] would check purplemux and install with npm if missing"
  purplemux_ready=true
elif command -v purplemux >/dev/null 2>&1; then
  info "Found purplemux ($(purplemux --version 2>/dev/null || echo unknown))"
  purplemux_ready=true
elif command -v npm >/dev/null 2>&1; then
  info "Installing purplemux via npm..."
  if npm install -g purplemux; then
    purplemux_ready=true
  fi
else
  warn "npm not found — install Node first (scripts/dev.sh), then run this script again."
fi

if $purplemux_ready; then
  install_agent "com.user.purplemux" \
                "$DOTFILES_DIR/configs/com.user.purplemux.plist" \
                "$DOTFILES_DIR/scripts/purplemux-launch.sh"
else
  warn "Skipping purplemux LaunchAgent because purplemux is not available."
fi

# ── code-server: brew-managed, scaffold config if missing ──
code_server_ready=false
if ! command -v code-server >/dev/null 2>&1; then
  warn "code-server not in PATH. Run 'brew bundle --file=$DOTFILES_DIR/Brewfile' first."
elif $DRY_RUN; then
  code_server_ready=true
else
  code_server_ready=true
fi

CODE_SERVER_CONFIG="$HOME/.config/code-server/config.yaml"
if [ ! -f "$CODE_SERVER_CONFIG" ]; then
  if $DRY_RUN; then
    info "[dry-run] would scaffold $CODE_SERVER_CONFIG"
  else
    mkdir -p "$(dirname "$CODE_SERVER_CONFIG")"
    # Generate a random password so the default install is not unauthenticated.
    pw=$(openssl rand -hex 12)
    cat > "$CODE_SERVER_CONFIG" <<EOF
bind-addr: 127.0.0.1:8088
auth: password
password: $pw
cert: false
EOF
    warn "Scaffolded $CODE_SERVER_CONFIG with a random password."
    warn "View it with: cat $CODE_SERVER_CONFIG"
  fi
elif ! grep -Eq '^[[:space:]]*bind-addr:[[:space:]]*127\.0\.0\.1:8088[[:space:]]*$' "$CODE_SERVER_CONFIG"; then
  warn "$CODE_SERVER_CONFIG does not bind to 127.0.0.1:8088."
  warn "For tailnet-only access, set: bind-addr: 127.0.0.1:8088"
fi

# Always lock the password file down — the chmod inside the scaffold branch
# only runs on a fresh install. Pre-existing files (e.g. from a prior
# code-server install that defaulted to 0644) need this.
if [ -f "$CODE_SERVER_CONFIG" ] && ! $DRY_RUN; then
  chmod 600 "$CODE_SERVER_CONFIG"
fi

if $code_server_ready; then
  install_agent "com.user.code-server" \
                "$DOTFILES_DIR/configs/com.user.code-server.plist" \
                "$DOTFILES_DIR/scripts/code-server-launch.sh"
else
  warn "Skipping code-server LaunchAgent because code-server is not available."
fi

info "services setup done"

# ── Auto-attach to tailnet via tailscale serve ──
# `tailscale serve` config is persisted by tailscaled, so this is idempotent —
# re-running with the same args is a no-op. We only attempt this if tailscale
# is installed AND the daemon is logged in (status is non-error).
if $DRY_RUN; then
  info "[dry-run] tailscale serve --bg --https=443  --set-path=/ http://localhost:8022"
  info "[dry-run] tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088"
elif command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; then
  tailscale serve --bg --https=443  --set-path=/ http://localhost:8022 \
    || warn "tailscale serve (purplemux) failed — run manually after login"
  tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088 \
    || warn "tailscale serve (code-server) failed — run manually after login"
  info "Tailnet exposure: purplemux on :443, code-server on :8443 (HTTPS via *.ts.net cert)"
else
  warn "Tailscale not installed or not logged in — skipping serve config."
  warn "After 'tailscale up', re-run this script or invoke manually:"
  warn "  tailscale serve --bg --https=443  --set-path=/ http://localhost:8022   # purplemux"
  warn "  tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088   # code-server"
fi
warn "Restrict Tailscale Serve access via ACL; do not expose purplemux's local :8022 listener directly."
