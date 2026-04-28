#!/bin/bash
set -euo pipefail
TAG="ssh"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── Enable Remote Login ──
info "Enabling macOS Remote Login (SSH server)..."
if $DRY_RUN; then
  info "[dry-run] sudo systemsetup -setremotelogin on"
else
  REMOTE_LOGIN=$(sudo systemsetup -getremotelogin 2>/dev/null | awk '{print $NF}')
  if [ "$REMOTE_LOGIN" = "On" ]; then
    info "Remote Login already enabled"
  else
    sudo systemsetup -setremotelogin on
    info "Remote Login enabled"
  fi
fi

# ── Generate host keys if missing ──
if ! $DRY_RUN; then
  if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
    info "Generating SSH host keys..."
    sudo ssh-keygen -A
  fi
fi

# ── Install hardened config ──
SSHD_CONFIG_DIR="/etc/ssh/sshd_config.d"
HARDENED_CONF="$SSHD_CONFIG_DIR/hardened.conf"
SSHD_MAIN="/etc/ssh/sshd_config"
INCLUDE_LINE="Include /etc/ssh/sshd_config.d/*.conf"
INCLUDE_ADDED_BY_US=false

info "Installing hardened sshd config..."
if $DRY_RUN; then
  info "[dry-run] sudo cp hardened.conf -> $HARDENED_CONF"
else
  sudo mkdir -p "$SSHD_CONFIG_DIR"

  if ! sudo grep -q "^Include.*sshd_config.d" "$SSHD_MAIN" 2>/dev/null; then
    warn "Adding Include directive to $SSHD_MAIN"
    echo "$INCLUDE_LINE" | sudo tee -a "$SSHD_MAIN" >/dev/null
    INCLUDE_ADDED_BY_US=true
  fi

  sed "s/__SSH_USER__/$(whoami)/g" "$DOTFILES_DIR/configs/sshd_config.d/hardened.conf" \
    | sudo tee "$HARDENED_CONF" >/dev/null
  sudo chmod 644 "$HARDENED_CONF"
  info "Installed: hardened.conf -> $HARDENED_CONF (AllowUsers=$(whoami))"
fi

# ── Validate and reload ──
if ! $DRY_RUN; then
  info "Validating sshd config..."
  if sudo sshd -t; then
    info "Config valid, reloading sshd..."
    sudo launchctl kickstart -k system/com.openssh.sshd 2>/dev/null || \
      sudo launchctl stop com.openssh.sshd 2>/dev/null || true
    info "sshd reloaded"
  else
    warn "sshd config validation failed (see error above)"
    warn "Reverting hardened config..."
    sudo rm -f "$HARDENED_CONF"
    if $INCLUDE_ADDED_BY_US; then
      warn "Reverting Include directive added to $SSHD_MAIN"
      sudo sed -i '' "\\|^${INCLUDE_LINE}\$|d" "$SSHD_MAIN"
    fi
    exit 1
  fi
fi

# ── Firewall check ──
info "Checking macOS firewall..."
if $DRY_RUN; then
  info "[dry-run] Skipping firewall check"
else
  FW_STATE=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | awk '{print $NF}' || echo "unknown")
  if [ "$FW_STATE" = "enabled." ]; then
    warn "Firewall is ON — make sure SSH (port 22) is allowed"
    warn "  Run: sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/sbin/sshd"
  else
    info "Firewall is off (SSH traffic will pass through)"
  fi
fi

# ── Initial key setup (temporary password auth) ──
if ! $DRY_RUN; then
  if [ ! -f "$HOME/.ssh/authorized_keys" ] || [ ! -s "$HOME/.ssh/authorized_keys" ]; then
    echo ""
    warn "No authorized_keys found — remote devices can't connect yet."
    read -rp "Temporarily enable password auth for ssh-copy-id? (y/N) " enable_pw
    if [[ "$enable_pw" == [yY] ]]; then
      # Ensure password auth is locked down on exit/interrupt
      lockdown() {
        sudo sed -i '' 's/PasswordAuthentication yes/PasswordAuthentication no/' "$HARDENED_CONF"
        sudo sed -i '' 's/AuthenticationMethods any/AuthenticationMethods publickey,keyboard-interactive:pam/' "$HARDENED_CONF"
        sudo launchctl kickstart -k system/com.openssh.sshd 2>/dev/null || true
        info "Password auth disabled — key-only access restored"
      }
      trap lockdown EXIT INT TERM

      sudo sed -i '' 's/PasswordAuthentication no/PasswordAuthentication yes/' "$HARDENED_CONF"
      sudo sed -i '' 's/AuthenticationMethods publickey,keyboard-interactive:pam/AuthenticationMethods any/' "$HARDENED_CONF"
      sudo launchctl kickstart -k system/com.openssh.sshd 2>/dev/null || true
      info "Password auth enabled temporarily"
      warn "From remote device, run: ssh-copy-id $(whoami)@$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP')"
      echo ""
      read -rp "Press Enter after you've copied the key to lock it back down..."
      lockdown
      trap - EXIT INT TERM
    fi
  fi
fi

echo ""
info "SSH server setup done"
warn "Test locally: ssh localhost"
