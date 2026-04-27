#!/bin/bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-false}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
info() { echo -e "${GREEN}[otp]${NC} $1"; }
warn() { echo -e "${YELLOW}[otp]${NC} $1"; }
error() { echo -e "${RED}[otp]${NC} $1"; }

# ── Check dependencies ──
if ! command -v google-authenticator &>/dev/null; then
  error "google-authenticator not found. Run: brew install google-authenticator-libpam"
  exit 1
fi

if ! command -v qrencode &>/dev/null; then
  warn "qrencode not found — QR code won't display. Run: brew install qrencode"
fi

# ── Find the PAM module ──
PAM_MODULE=""
for candidate in \
  "$(brew --prefix)/lib/security/pam_google_authenticator.so" \
  "$(brew --prefix)/lib/pam_google_authenticator.so" \
  "/usr/local/lib/security/pam_google_authenticator.so" \
  "/opt/homebrew/lib/security/pam_google_authenticator.so"; do
  if [ -f "$candidate" ]; then
    PAM_MODULE="$candidate"
    break
  fi
done

if [ -z "$PAM_MODULE" ]; then
  error "Could not find pam_google_authenticator.so"
  error "Try: brew reinstall google-authenticator-libpam"
  exit 1
fi

info "Found PAM module: $PAM_MODULE"

# ── Generate TOTP secret ──
echo ""
echo "=== TOTP Setup ==="
echo ""
echo "This will generate a TOTP secret for your account."
echo "You'll scan a QR code with your authenticator app (Google Authenticator, Authy, etc.)."
echo ""

if [ -f "$HOME/.google_authenticator" ]; then
  warn "TOTP already configured (~/.google_authenticator exists)"
  read -rp "Reconfigure? (y/N) " reconfigure
  if [[ "$reconfigure" != [yY] ]]; then
    info "Keeping existing TOTP config"
  else
    if ! $DRY_RUN; then
      google-authenticator -t -d -f -r 3 -R 30 -w 3
    else
      info "[dry-run] google-authenticator -t -d -f -r 3 -R 30 -w 3"
    fi
  fi
else
  if $DRY_RUN; then
    info "[dry-run] google-authenticator -t -d -f -r 3 -R 30 -w 3"
  else
    google-authenticator -t -d -f -r 3 -R 30 -w 3
  fi
fi

# Flags explanation:
#   -t  Time-based (TOTP)
#   -d  Disallow reuse of tokens
#   -f  Force overwrite
#   -r 3 -R 30  Rate limit: 3 attempts per 30 seconds
#   -w 3  Allow 3 window codes (±90 sec skew)

# ── Configure PAM ──
PAM_SSHD="/etc/pam.d/sshd"
PAM_LINE="auth required $PAM_MODULE"

info "Configuring PAM for SSH..."
if $DRY_RUN; then
  info "[dry-run] Add google-authenticator to $PAM_SSHD"
else
  if grep -q "pam_google_authenticator" "$PAM_SSHD" 2>/dev/null; then
    info "PAM already configured for google-authenticator"
  else
    warn "Adding google-authenticator to $PAM_SSHD (requires sudo)"
    # Backup original
    sudo cp "$PAM_SSHD" "${PAM_SSHD}.backup.$(date +%Y%m%d)"
    # Add at the end
    echo "$PAM_LINE" | sudo tee -a "$PAM_SSHD" >/dev/null
    info "PAM configured"
  fi
fi

# ── Verify sshd_config has correct AuthenticationMethods ──
info "Verifying sshd AuthenticationMethods..."
if grep -rq "AuthenticationMethods.*publickey.*keyboard-interactive" /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>/dev/null; then
  info "AuthenticationMethods already set (publickey + keyboard-interactive)"
else
  warn "AuthenticationMethods not found in sshd config"
  warn "Run ssh-server.sh first to install the hardened config"
fi

# ── Ensure ChallengeResponseAuthentication is enabled ──
# macOS uses ChallengeResponseAuthentication in older versions
if ! $DRY_RUN; then
  if grep -q "^ChallengeResponseAuthentication no" /etc/ssh/sshd_config 2>/dev/null; then
    warn "Enabling ChallengeResponseAuthentication in sshd_config"
    sudo sed -i '' 's/^ChallengeResponseAuthentication no/ChallengeResponseAuthentication yes/' /etc/ssh/sshd_config
  fi
fi

# ── Reload sshd ──
if ! $DRY_RUN; then
  info "Reloading sshd..."
  if sudo sshd -t; then
    sudo launchctl kickstart -k system/com.openssh.sshd 2>/dev/null || \
      sudo launchctl stop com.openssh.sshd 2>/dev/null || true
    info "sshd reloaded"
  else
    error "sshd config validation failed — check config"
    exit 1
  fi
fi

echo ""
info "OTP setup done"
warn "Test: ssh localhost (should ask for SSH key + verification code)"
warn "IMPORTANT: Save your emergency scratch codes somewhere safe!"
