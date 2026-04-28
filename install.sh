#!/bin/bash
set -euo pipefail

DOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"
HONE_DIR="$HOME/Documents/hone-english"  # also used in claude-settings.json via __HONE_DIR__
DRY_RUN=false

for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

export DOTFILES_DIR HONE_DIR DRY_RUN

TAG="install"
# shellcheck source=scripts/lib/common.sh
source "$DOTFILES_DIR/scripts/lib/common.sh"

if $DRY_RUN; then
  warn "=== DRY RUN MODE — no changes will be made ==="
fi

echo ""
echo "========================================="
echo "  macOS dev environment setup (dotfiles)"
echo "========================================="
echo ""
echo "The following will be installed/configured:"
echo "  1. Homebrew & apps (brew.sh + Brewfile)"
echo "  2. macOS system settings (macos.sh)"
echo "  3. Dev tools: nvm, pyenv, etc. (dev.sh)"
echo "  4. Shell — Oh My Zsh + plugins (shell.sh)"
echo "  5. Git — config + SSH keys (git.sh)"
echo "  6. Claude Code setup (claude.sh)"
echo "  7. opencode setup (opencode.sh)"
echo "  8. dotfiles symlinks"
echo "  9. hone-english (Claude Code hooks)"
echo " 10. SSH server (ssh-server.sh)"
echo " 11. Tailscale VPN (tailscale.sh)"
echo " 12. OTP two-factor auth (otp.sh)"
echo ""

read -rp "Ready to continue? (y/N) " confirm
if [[ "$confirm" != [yY] ]]; then
  echo "Aborted."
  exit 0
fi

# ── 1. Homebrew ──
info "1/12 Installing Homebrew & apps..."
bash "$DOTFILES_DIR/scripts/brew.sh"

# ── 2. macOS settings ──
info "2/12 Applying macOS system settings..."
bash "$DOTFILES_DIR/scripts/macos.sh"

# ── 3. Dev environment ──
info "3/12 Setting up dev environment..."
bash "$DOTFILES_DIR/scripts/dev.sh"

# ── 4. Shell ──
info "4/12 Configuring shell environment..."
bash "$DOTFILES_DIR/scripts/shell.sh"

# ── 5. Git ──
info "5/12 Configuring Git..."
bash "$DOTFILES_DIR/scripts/git.sh"

# ── 6. Claude Code ──
info "6/12 Setting up Claude Code..."
bash "$DOTFILES_DIR/scripts/claude.sh"

# ── 7. opencode ──
info "7/12 Setting up opencode..."
bash "$DOTFILES_DIR/scripts/opencode.sh"

# ── 8. Symlinks ──
info "8/12 Creating dotfiles symlinks..."

link_file "$DOTFILES_DIR/configs/.zshrc"              "$HOME/.zshrc"
link_file "$DOTFILES_DIR/configs/.gitconfig"           "$HOME/.gitconfig"
link_file "$DOTFILES_DIR/configs/.gitconfig-personal"  "$HOME/.gitconfig-personal"
link_file "$DOTFILES_DIR/configs/.gitconfig-work"      "$HOME/.gitconfig-work"

# shared agent config (canonical)
mkdir -p "$HOME/.agent"
link_file "$DOTFILES_DIR/configs/AGENTS.md" "$HOME/.agent/AGENTS.md"

# Claude Code
mkdir -p "$HOME/.claude/hooks" "$HOME/.claude/plugins"
if $DRY_RUN; then
  info "[dry-run] Generate ~/.claude/settings.json (HONE_DIR=$HONE_DIR)"
else
  hone_dir_escaped=$(printf '%s\n' "$HONE_DIR" | sed 's/[\&|]/\\&/g')
  sed "s|__HONE_DIR__|${hone_dir_escaped}|g" \
    "$DOTFILES_DIR/configs/claude-settings.json" > "$HOME/.claude/settings.json"
  info "Generated: claude-settings.json -> ~/.claude/settings.json"
fi
link_file "$DOTFILES_DIR/configs/CLAUDE.md"           "$HOME/.claude/CLAUDE.md"
link_file "$DOTFILES_DIR/configs/hooks/skill-eval.sh" "$HOME/.claude/hooks/skill-eval.sh"

# Cursor
mkdir -p "$HOME/.cursor/rules"
link_file "$DOTFILES_DIR/configs/AGENTS.md" "$HOME/.cursor/rules/AGENTS.md"

# opencode AGENTS.md (opencode.sh handles its own config files)
mkdir -p "$HOME/.config/opencode"
link_file "$DOTFILES_DIR/configs/AGENTS.md" "$HOME/.config/opencode/AGENTS.md"

RTK_CONFIG_DIR="$HOME/Library/Application Support/rtk"
mkdir -p "$RTK_CONFIG_DIR"
link_file "$DOTFILES_DIR/configs/rtk-config.toml"     "$RTK_CONFIG_DIR/config.toml"

# ── 9. hone-english ──
info "9/12 Cloning hone-english..."
if [ -d "$HONE_DIR" ]; then
  info "hone-english already exists, skipping"
elif $DRY_RUN; then
  info "[dry-run] git clone https://github.com/dididy/hone-english $HONE_DIR"
else
  git clone https://github.com/dididy/hone-english "$HONE_DIR"
  info "Cloned: hone-english → $HONE_DIR"
fi

# ── 10. SSH server ──
info "10/12 Setting up SSH server..."
bash "$DOTFILES_DIR/scripts/ssh-server.sh"

# ── 11. Tailscale ──
info "11/12 Setting up Tailscale..."
bash "$DOTFILES_DIR/scripts/tailscale.sh"

# ── 12. OTP ──
info "12/12 Setting up OTP two-factor auth..."
bash "$DOTFILES_DIR/scripts/otp.sh"

echo ""
info "Done."
info "Restart your terminal or run 'source ~/.zshrc'."
