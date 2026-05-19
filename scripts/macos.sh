#!/bin/bash
set -euo pipefail
TAG="macos"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

run_defaults() { run_or_dry "defaults" defaults "$@"; }

# ── Dock ──
info "Configuring Dock..."
run_defaults write com.apple.dock autohide -bool true
run_defaults write com.apple.dock tilesize -int 36
run_defaults write com.apple.dock show-recents -bool false
run_defaults write com.apple.dock minimize-to-application -bool true
# Enable "Show Desktop" trackpad gesture
run_defaults write com.apple.dock showDesktopGestureEnabled -bool true

# ── Finder ──
info "Configuring Finder..."
run_defaults write com.apple.finder AppleShowAllFiles -bool true
run_defaults write com.apple.finder ShowPathbar -bool true
run_defaults write com.apple.finder ShowStatusBar -bool true
run_defaults write com.apple.finder _FXShowPosixPathInTitle -bool true
run_defaults write NSGlobalDomain AppleShowAllExtensions -bool true
# Disable extension change warning
run_defaults write com.apple.finder FXEnableExtensionChangeWarning -bool false

# ── Keyboard ──
info "Configuring keyboard..."
run_defaults write NSGlobalDomain KeyRepeat -int 1
run_defaults write NSGlobalDomain InitialKeyRepeat -int 10
run_defaults write NSGlobalDomain ApplePressAndHoldEnabled -bool false
# Disable typing "intelligence" that mangles code/markdown
run_defaults write NSGlobalDomain NSAutomaticSpellingCorrectionEnabled -bool false
run_defaults write NSGlobalDomain NSAutomaticQuoteSubstitutionEnabled -bool false
run_defaults write NSGlobalDomain NSAutomaticDashSubstitutionEnabled -bool false
run_defaults write NSGlobalDomain NSAutomaticPeriodSubstitutionEnabled -bool false
run_defaults write NSGlobalDomain NSAutomaticCapitalizationEnabled -bool false

# CapsLock → Escape (persistent via hidutil + LaunchAgent)
info "Mapping CapsLock → Escape..."
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
# Some setups end up with ~/Library/LaunchAgents owned by root (e.g. from a
# prior `sudo ./install.sh` mistake, or a third-party installer that ran as
# root). In that state we can't write our plists. Fix it once with sudo.
if [ -d "$LAUNCH_AGENTS_DIR" ] && [ ! -w "$LAUNCH_AGENTS_DIR" ]; then
  if $DRY_RUN; then
    info "[dry-run] sudo chown -R $(whoami):staff $LAUNCH_AGENTS_DIR"
  else
    warn "$LAUNCH_AGENTS_DIR is not writable — fixing ownership (sudo)"
    sudo chown -R "$(whoami):$(id -gn)" "$LAUNCH_AGENTS_DIR"
  fi
fi
if ! $DRY_RUN; then
  mkdir -p "$LAUNCH_AGENTS_DIR"
  cat > "$LAUNCH_AGENTS_DIR/com.user.capslock-escape.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.user.capslock-escape</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/hidutil</string>
    <string>property</string>
    <string>--set</string>
    <string>{"UserKeyMapping":[{"HIDKeyboardModifierMappingSrc":0x700000039,"HIDKeyboardModifierMappingDst":0x700000029}]}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
PLIST
  launchctl load "$LAUNCH_AGENTS_DIR/com.user.capslock-escape.plist" 2>/dev/null || true
  hidutil property --set '{"UserKeyMapping":[{"HIDKeyboardModifierMappingSrc":0x700000039,"HIDKeyboardModifierMappingDst":0x700000029}]}'
else
  info "[dry-run] Skipping CapsLock → Escape"
fi

# Input source switch → Command+Space, Spotlight → Option+Space
info "Configuring input source / Spotlight shortcuts..."
# Spotlight: move to Option+Space (key 64 = Show Spotlight search)
run_defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys -dict-add 64 \
  "<dict><key>enabled</key><true/><key>value</key><dict><key>type</key><string>standard</string><key>parameters</key><array><integer>32</integer><integer>49</integer><integer>524288</integer></array></dict></dict>"
# Disable Spotlight window shortcut (key 65)
run_defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys -dict-add 65 \
  "<dict><key>enabled</key><false/></dict>"
# Disable previous input source shortcut (key 60) — use key 61 only
run_defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys -dict-add 60 \
  "<dict><key>enabled</key><false/></dict>"
# Input source switch (next source) → Command+Space (key 61)
run_defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys -dict-add 61 \
  "<dict><key>enabled</key><true/><key>value</key><dict><key>type</key><string>standard</string><key>parameters</key><array><integer>32</integer><integer>49</integer><integer>1048576</integer></array></dict></dict>"
# Apply shortcut changes immediately
if ! $DRY_RUN; then
  /System/Library/PrivateFrameworks/SystemAdministration.framework/Resources/activateSettings -u
fi

# Input sources: ensure ABC + Korean 2-Set are both enabled so Cmd+Space has
# something to toggle between. The shortcut above is a no-op when only one
# source is registered. We touch HIToolbox's enabled-sources array idempotently
# (only writing if Korean is absent) so re-running is safe.
if ! $DRY_RUN; then
  if ! defaults read com.apple.HIToolbox AppleEnabledInputSources 2>/dev/null \
        | grep -q "com.apple.inputmethod.Korean.2SetKorean"; then
    info "Adding Korean 2-Set to enabled input sources"
    /usr/libexec/PlistBuddy -c "Add :AppleEnabledInputSources: dict" \
      ~/Library/Preferences/com.apple.HIToolbox.plist 2>/dev/null || true
    /usr/libexec/PlistBuddy \
      -c "Add :AppleEnabledInputSources:0:\"Bundle ID\" string com.apple.inputmethod.Korean" \
      -c "Add :AppleEnabledInputSources:0:\"Input Mode\" string com.apple.inputmethod.Korean.2SetKorean" \
      -c "Add :AppleEnabledInputSources:0:InputSourceKind string \"Input Mode\"" \
      ~/Library/Preferences/com.apple.HIToolbox.plist 2>/dev/null \
      || warn "Failed to add Korean input source — add it manually in System Settings > Keyboard > Input Sources"
    warn "Korean input source added — log out/in (or restart) for Cmd+Space toggle to start working"
  else
    info "Korean input source already enabled ✓"
  fi
fi

# ── Trackpad ──
info "Configuring trackpad..."
run_defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad Clicking -bool true
run_defaults write NSGlobalDomain com.apple.swipescrolldirection -bool true
# Three-finger drag (via Accessibility path)
run_defaults write com.apple.AppleMultitouchTrackpad TrackpadThreeFingerDrag -bool true
run_defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad TrackpadThreeFingerDrag -bool true

# ── Screenshots ──
info "Configuring screenshots..."
SCREENSHOT_DIR="$HOME/Screenshots"
if ! $DRY_RUN; then
  mkdir -p "$SCREENSHOT_DIR"
fi
run_defaults write com.apple.screencapture location -string "$SCREENSHOT_DIR"
run_defaults write com.apple.screencapture type -string "png"

# ── Remote Login (SSH) ──
info "Enabling Remote Login (SSH)..."
if $DRY_RUN; then
  info "[dry-run] Skipping Remote Login enable"
else
  sudo systemsetup -setremotelogin on 2>/dev/null || info "⚠️  Remote Login enable failed — enable manually in System Settings > General > Sharing"
fi

# ── Misc ──
info "Other settings..."
# Don't create .DS_Store on network/USB drives
run_defaults write com.apple.desktopservices DSDontWriteNetworkStores -bool true
run_defaults write com.apple.desktopservices DSDontWriteUSBStores -bool true

# Apply changes
if ! $DRY_RUN; then
  killall Dock 2>/dev/null || true
  killall Finder 2>/dev/null || true
  killall SystemUIServer 2>/dev/null || true
fi

# ── Touch ID for sudo ──
info "Configuring Touch ID for sudo..."
TOUCHID_CONF="/etc/pam.d/sudo_local"
TOUCHID_TEMPLATE="/etc/pam.d/sudo_local.template"
if $DRY_RUN; then
  info "[dry-run] Would enable pam_tid.so in $TOUCHID_CONF"
else
  if [ -f "$TOUCHID_CONF" ] && grep -Eq '^[[:space:]]*auth[[:space:]]+sufficient[[:space:]]+pam_tid\.so' "$TOUCHID_CONF" 2>/dev/null; then
    info "Touch ID for sudo already enabled"
  else
    if [ ! -f "$TOUCHID_CONF" ] && [ ! -f "$TOUCHID_TEMPLATE" ]; then
      warn "/etc/pam.d/sudo_local.template missing — your macOS may not support sudo_local; skipping"
    else
      if [ -f "$TOUCHID_CONF" ]; then
        backup_dst="$(next_backup_path "$TOUCHID_CONF")"
        info "Backing up $TOUCHID_CONF -> $backup_dst (will require sudo)"
        sudo cp -p "$TOUCHID_CONF" "$backup_dst"
      else
        info "Creating $TOUCHID_CONF from template (will require sudo)"
        sudo cp -p "$TOUCHID_TEMPLATE" "$TOUCHID_CONF"
      fi
      printf '\n%s\n' 'auth       sufficient     pam_tid.so' | sudo tee -a "$TOUCHID_CONF" > /dev/null
      sudo chmod 644 "$TOUCHID_CONF"
      info "Touch ID for sudo enabled — try 'sudo -k && sudo true' to verify"
    fi
  fi
fi

# ── Application Firewall + stealth mode ──
# Defense-in-depth alongside Tailscale: even if a dev server binds to
# 0.0.0.0 by accident, stealth mode makes the cafe-wifi attacker's
# port scan see closed ports instead of open ones.
info "Configuring macOS Application Firewall..."
FW_TOOL="/usr/libexec/ApplicationFirewall/socketfilterfw"
if [ ! -x "$FW_TOOL" ]; then
  warn "$FW_TOOL not found — skipping firewall config"
elif $DRY_RUN; then
  info "[dry-run] would enable firewall + stealth + signed-allow"
else
  sudo "$FW_TOOL" --setglobalstate on        > /dev/null
  sudo "$FW_TOOL" --setstealthmode on        > /dev/null
  sudo "$FW_TOOL" --setallowsigned on        > /dev/null
  sudo "$FW_TOOL" --setallowsignedapp on     > /dev/null
  info "Firewall: ON, stealth: ON, signed apps: allowed"
fi

info "macOS settings done"
