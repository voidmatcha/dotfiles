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

# ── Local plugins ──
link_file "$DOTFILES_DIR/configs/opencode/plugins" \
          "$OPENCODE_CONFIG_DIR/plugins"

# ── Discord notify secrets (Discord webhook + user ID) ──
# Scaffold a chmod-600 file outside the dotfiles repo so secrets never touch git.
SECRETS_FILE="$HOME/.opencode-secrets.env"
if $DRY_RUN; then
  info "[dry-run] would scaffold $SECRETS_FILE (chmod 600)"
elif [ ! -f "$SECRETS_FILE" ]; then
  cat > "$SECRETS_FILE" <<'ENV'
# opencode secrets — sourced by scripts/opencode-web-launch.sh.
# Keep chmod 600 (owner read/write only).
#
# Discord notify plugin (configs/opencode/plugins/discord-notify.ts):
#DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
#DISCORD_USER_ID="123456789012345678"
ENV
  chmod 600 "$SECRETS_FILE"
  warn "Scaffolded $SECRETS_FILE — fill in DISCORD_WEBHOOK_URL and DISCORD_USER_ID"
else
  current_perms=$(stat -f '%Lp' "$SECRETS_FILE")
  if [ "$current_perms" != "600" ]; then
    chmod 600 "$SECRETS_FILE"
    info "Reset perms on $SECRETS_FILE: $current_perms -> 600"
  fi
fi

# ── opencode web LaunchAgent ──
# Wrapper is copied into ~/.local/bin/ so launchd can execute it regardless of
# where the dotfiles repo lives — ~/Downloads, ~/Documents, etc. carry macOS
# TCC restrictions that block launchd-spawned processes from reading them.
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
WRAPPER_SRC="$DOTFILES_DIR/scripts/opencode-web-launch.sh"
WRAPPER_DST="$HOME/.local/bin/opencode-web-launch.sh"
PLIST_DST="$LAUNCH_AGENTS_DIR/com.user.opencode-web.plist"
PLIST_SRC="$DOTFILES_DIR/configs/com.user.opencode-web.plist"
PLIST_LABEL="com.user.opencode-web"

if $DRY_RUN; then
  info "[dry-run] would install wrapper to $WRAPPER_DST and load $PLIST_LABEL"
else
  mkdir -p "$LAUNCH_AGENTS_DIR" "$HOME/Library/Logs" "$HOME/.local/bin"
  install -m 755 "$WRAPPER_SRC" "$WRAPPER_DST"
  sed -e "s|__WRAPPER_PATH__|$WRAPPER_DST|g" \
      -e "s|__HOME__|$HOME|g" \
      "$PLIST_SRC" > "$PLIST_DST"
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  launchctl load "$PLIST_DST"
  info "LaunchAgent installed: $PLIST_LABEL (port 4096, binds to Tailscale IP)"
fi

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
warn "npm plugins in opencode.json auto-install on first invocation (Bun cache)."
warn "Local plugins live at configs/opencode/plugins/ and load directly via Bun."
warn "After setting DISCORD_WEBHOOK_URL/DISCORD_USER_ID, restart the LaunchAgent:"
warn "  launchctl kickstart -k gui/\$(id -u)/com.user.opencode-web"
