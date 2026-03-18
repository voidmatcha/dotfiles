#!/bin/bash
set -euo pipefail

DOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"
HONE_DIR="$HOME/Documents/hone-english"  # also used in claude-settings.json via __HONE_DIR__
DRY_RUN=false

# Parse arguments
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

export DOTFILES_DIR HONE_DIR DRY_RUN

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

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
echo "  7. dotfiles symlinks"
echo "  8. hone-english (Claude Code hooks)"
echo ""

read -rp "Ready to continue? (y/N) " confirm
if [[ "$confirm" != [yY] ]]; then
  echo "Aborted."
  exit 0
fi

# ── 1. Homebrew ──
info "1/8 Installing Homebrew & apps..."
bash "$DOTFILES_DIR/scripts/brew.sh"

# ── 2. macOS settings ──
info "2/8 Applying macOS system settings..."
bash "$DOTFILES_DIR/scripts/macos.sh"

# ── 3. Dev environment ──
info "3/8 Setting up dev environment..."
bash "$DOTFILES_DIR/scripts/dev.sh"

# ── 4. Shell ──
info "4/8 Configuring shell environment..."
bash "$DOTFILES_DIR/scripts/shell.sh"

# ── 5. Git ──
info "5/8 Configuring Git..."
bash "$DOTFILES_DIR/scripts/git.sh"

# ── 6. Claude Code ──
info "6/8 Setting up Claude Code..."
bash "$DOTFILES_DIR/scripts/claude.sh"

# ── 7. Symlinks ──
info "7/8 Creating dotfiles symlinks..."

link_file() {
  local src="$1"
  local dst="$2"

  if $DRY_RUN; then
    info "[dry-run] ln -sf $src → $dst"
    return
  fi

  if [ -f "$dst" ] && [ ! -L "$dst" ]; then
    warn "Backing up $dst → ${dst}.backup"
    mv "$dst" "${dst}.backup"
  fi

  ln -sf "$src" "$dst"
  info "Linked: $src → $dst"
}

link_file "$DOTFILES_DIR/configs/.zshrc"              "$HOME/.zshrc"
link_file "$DOTFILES_DIR/configs/.gitconfig"           "$HOME/.gitconfig"
link_file "$DOTFILES_DIR/configs/.gitconfig-personal"  "$HOME/.gitconfig-personal"
link_file "$DOTFILES_DIR/configs/.gitconfig-work"      "$HOME/.gitconfig-work"

mkdir -p "$HOME/.config"
link_file "$DOTFILES_DIR/configs/starship.toml"        "$HOME/.config/starship.toml"

mkdir -p "$HOME/.claude/hooks" "$HOME/.claude/plugins"
if $DRY_RUN; then
  info "[dry-run] Generate ~/.claude/settings.json (HONE_DIR=$HONE_DIR)"
else
  sed "s|__HONE_DIR__|$HONE_DIR|g" "$DOTFILES_DIR/configs/claude-settings.json" > "$HOME/.claude/settings.json"
  info "Generated: claude-settings.json → ~/.claude/settings.json"
fi
link_file "$DOTFILES_DIR/configs/CLAUDE.md"            "$HOME/.claude/CLAUDE.md"
link_file "$DOTFILES_DIR/configs/hooks/skill-eval.sh"  "$HOME/.claude/hooks/skill-eval.sh"
chmod +x "$DOTFILES_DIR/configs/hooks/skill-eval.sh"

RTK_CONFIG_DIR="$HOME/Library/Application Support/rtk"
mkdir -p "$RTK_CONFIG_DIR"
link_file "$DOTFILES_DIR/configs/rtk-config.toml"     "$RTK_CONFIG_DIR/config.toml"

# ── 8. hone-english ──
info "8/8 Cloning hone-english..."
if [ -d "$HONE_DIR" ]; then
  info "hone-english already exists, skipping"
elif $DRY_RUN; then
  info "[dry-run] git clone https://github.com/dididy/hone-english $HONE_DIR"
else
  git clone https://github.com/dididy/hone-english "$HONE_DIR"
  info "Cloned: hone-english → $HONE_DIR"
fi

echo ""
info "Done."
info "Restart your terminal or run 'source ~/.zshrc'."
