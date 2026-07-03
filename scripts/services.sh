#!/bin/bash
set -euo pipefail
TAG="services"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# Installs LaunchAgents for purplemux, code-server, agentwatch, and caffeinate, but skips loading LaunchAgents when dependencies are missing.
# Each installed service runs at
# login and is auto-restarted (KeepAlive=true). code-server binds to 127.0.0.1 (kernel-
# level isolation). purplemux binds to *:8022 (no --bind flag upstream), so this
# repo relies on Tailscale Serve plus the macOS firewall rather than an app-level
# tailnet filter. Both are exposed via `tailscale serve` so the public-facing
# transport is HTTPS over the tailnet (cert from Tailscale, not from the app).

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

# Restore the latest nvm-managed Node bin for non-interactive service setup.
# install.sh invokes scripts/dev.sh and scripts/services.sh as separate shells,
# so nvm's PATH mutations from dev.sh do not automatically carry over.
if [ -d "$HOME/.nvm/versions/node" ]; then
  # Highest installed semver (sort -V), matching scripts/purplemux-launch.sh.
  # ls -dt sorts by mtime and can pick an older
  # Node that a freshly built newer one was layered on top of.
  latest_node="$(find "$HOME/.nvm/versions/node" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort -V | tail -n1 || true)"
  if [ -n "$latest_node" ] && [ -d "$HOME/.nvm/versions/node/$latest_node/bin" ]; then
    latest_node_bin="$HOME/.nvm/versions/node/$latest_node/bin"
    export PATH="$latest_node_bin:$PATH"
  fi
fi

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
      warn "Then check logs: tail -n 80 $HOME/Library/Logs/${label##*.}.err.log"
      return 0
    fi
  fi

  info "LaunchAgent installed: $label"
}

# ── purplemux: source-checkout shim (opt-in) ──
# Set PURPLEMUX_APP_DIR to run purplemux from a source checkout instead of the
# npm global. The shim template lives in the repo (scripts/purplemux-shim.sh)
# and is rendered + installed with `install -m 755`, so a hand-made shim can
# never silently lose its exec bit or drift off the tracked path again.
# TCC-protected folders are refused: launchd cannot answer a consent prompt,
# so a checkout under ~/Documents|~/Desktop|~/Downloads hangs the LaunchAgent.
under_tcc_protected_dir() {
  case "$1" in
    "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*) return 0 ;;
  esac
  return 1
}
if [ -n "${PURPLEMUX_APP_DIR:-}" ]; then
  if under_tcc_protected_dir "$PURPLEMUX_APP_DIR"; then
    warn "PURPLEMUX_APP_DIR=$PURPLEMUX_APP_DIR is under a TCC-protected folder — launchd would hang, not prompt. Move the checkout (e.g. ~/dev/cmux-purplemux) and re-run. Skipping shim install."
  elif $DRY_RUN; then
    info "[dry-run] would render purplemux shim for $PURPLEMUX_APP_DIR to $HOME/.local/bin/purplemux (install -m 755)"
  else
    mkdir -p "$HOME/.local/bin"
    purplemux_shim_tmp="$(mktemp)"
    sed -e "s|__PURPLEMUX_APP_DIR__|$PURPLEMUX_APP_DIR|g" \
        "$DOTFILES_DIR/scripts/purplemux-shim.sh" > "$purplemux_shim_tmp"
    install -m 755 "$purplemux_shim_tmp" "$HOME/.local/bin/purplemux"
    rm -f "$purplemux_shim_tmp"
    info "purplemux shim installed: $HOME/.local/bin/purplemux -> $PURPLEMUX_APP_DIR"
  fi
fi

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

# ── agentwatch: ensure global install (bun preferred), run supervise loop ──
# bun is preferred because `bun install -g` uses a single stable bin
# (~/.bun/bin), avoiding nvm's per-Node-version global-bin fragility. npm is the
# fallback when bun is absent. bun is already a managed dependency (Brewfile).
agentwatch_ready=false
agentwatch_launch_path=""
agentwatch_stable_path="/opt/homebrew/bin:/usr/local/bin:$HOME/.bun/bin:$HOME/.local/bin:/usr/bin:/bin"
if $DRY_RUN; then
  info "[dry-run] would check agentwatch and install @voidmatcha/agentwatch (bun preferred, npm fallback)"
  agentwatch_ready=true
elif agentwatch_launch_path=$(PATH="$agentwatch_stable_path" command -v agentwatch 2>/dev/null); then
  info "Found agentwatch ($($agentwatch_launch_path --version 2>/dev/null || echo unknown))"
  agentwatch_ready=true
elif command -v bun >/dev/null 2>&1; then
  info "Installing @voidmatcha/agentwatch via bun..."
  if bun install -g @voidmatcha/agentwatch; then
    agentwatch_ready=true
  fi
elif command -v npm >/dev/null 2>&1; then
  info "Installing @voidmatcha/agentwatch via npm..."
  if npm install -g @voidmatcha/agentwatch; then
    agentwatch_ready=true
  fi
else
  warn "Neither bun nor npm found — run 'brew bundle' / scripts/dev.sh first, then re-run."
fi

if $agentwatch_ready; then
  install_agent "com.user.agentwatch"                 "$DOTFILES_DIR/configs/com.user.agentwatch.plist"                 "$DOTFILES_DIR/scripts/agentwatch-launch.sh"
else
  warn "Skipping agentwatch LaunchAgent because agentwatch is not available in launchd's stable PATH."
fi

# ── caffeinate: keep the Mac awake on AC for remote access ──
# caffeinate is built into macOS (no install, no sudo). `-s` prevents system sleep
# only on AC power (battery still sleeps), and the assertion exists only while the
# process runs — so this LaunchAgent keeps Tailscale SSH / code-server / agentwatch
# reachable without any persistent pmset change. (Lid-closed sleep is not covered;
# that needs `sudo pmset -c disablesleep 1`.)
install_agent "com.user.caffeinate" \
              "$DOTFILES_DIR/configs/com.user.caffeinate.plist" \
              "$DOTFILES_DIR/scripts/caffeinate-launch.sh"

# ── Auto-attach to tailnet via tailscale serve ──
# `tailscale serve` config is persisted by tailscaled, so re-running with the
# same args is a no-op. Because it exposes local services to the tailnet, it is
# opt-in and should only be enabled after confirming Tailscale ACLs.
if $DRY_RUN; then
  info "[dry-run] tailscale serve opt-in is ENABLE_TAILSCALE_SERVE=1"
  info "[dry-run] tailscale serve --bg --https=443  --set-path=/ http://localhost:8022"
  info "[dry-run] tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088"
elif [ "${ENABLE_TAILSCALE_SERVE:-0}" = "1" ] && command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; then
  tailscale serve --bg --https=443  --set-path=/ http://localhost:8022     || warn "tailscale serve (purplemux) failed — run manually after login"
  tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088     || warn "tailscale serve (code-server) failed — run manually after login"
  info "Tailnet exposure: purplemux on :443, code-server on :8443 (HTTPS via *.ts.net cert)"
else
  if [ "${ENABLE_TAILSCALE_SERVE:-0}" != "1" ]; then
    warn "Skipping tailscale serve config; set ENABLE_TAILSCALE_SERVE=1 after confirming ACLs."
  else
    warn "Tailscale not installed or not logged in — skipping serve config."
  fi
  warn "Run after login if desired:"
  warn "  ENABLE_TAILSCALE_SERVE=1 bash scripts/services.sh"
  warn "  tailscale serve --bg --https=443 --set-path=/ http://localhost:8022"
  warn "  tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088"
  warn "Restrict Tailscale Serve access via ACL; do not expose purplemux's local :8022 listener directly."
fi

info "services setup done"
