#!/bin/bash
set -euo pipefail

# Refuse to run as root. Homebrew rejects root execution, oh-my-zsh installs
# into the wrong $HOME, and ~/Library/LaunchAgents/ ownership gets corrupted
# (the install ends up writing root-owned files into the user's tree, which
# is exactly the bug that prompted this guard). Individual steps will call
# sudo themselves where they need it.
if [ "$EUID" -eq 0 ]; then
  echo "✗ Do NOT run install.sh with sudo or as root."           >&2
  echo "  Run as your normal user: ./install.sh"                  >&2
  echo "  Individual steps (firewall, Remote Login) will sudo"   >&2
  echo "  themselves and prompt for your password as needed."    >&2
  exit 1
fi

DOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN=false
NON_INTERACTIVE=false
ASSUME_YES=false

for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    --yes|-y) ASSUME_YES=true ;;
    --non-interactive) NON_INTERACTIVE=true; ASSUME_YES=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

if $DRY_RUN; then
  NON_INTERACTIVE=true
  ASSUME_YES=true
fi

export DOTFILES_DIR DRY_RUN NON_INTERACTIVE

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
echo "  6. dotfiles symlinks"
echo "  7. Claude Code setup (claude.sh)"
echo "  8. Codex CLI setup (codex.sh)"
echo "  9. Hermes Agent (hermes.sh)"
echo " 10. Tailscale VPN + Tailscale SSH (tailscale.sh)"
echo " 11. purplemux + code-server LaunchAgents (services.sh)"
echo " 12. Company overlay (only if the company/ submodule is initialized)"
echo ""

if $ASSUME_YES; then
  info "Proceeding without confirmation"
else
  read -rp "Ready to continue? (y/N) " confirm
  if [[ "$confirm" != [yY] ]]; then
    echo "Aborted."
    exit 0
  fi
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

# ── 6. Symlinks ──
info "6/12 Creating dotfiles symlinks..."

link_file "$DOTFILES_DIR/configs/.zshrc"              "$HOME/.zshrc"
link_file "$DOTFILES_DIR/configs/.tmux.conf"          "$HOME/.tmux.conf"
link_file "$DOTFILES_DIR/configs/.gitconfig"           "$HOME/.gitconfig"
link_file "$DOTFILES_DIR/configs/.gitconfig-personal"  "$HOME/.gitconfig-personal"
link_file "$DOTFILES_DIR/configs/.gitconfig-work"      "$HOME/.gitconfig-work"
link_file "$DOTFILES_DIR/configs/.gitignore_global"    "$HOME/.gitignore_global"

# shared agent config (canonical)
ensure_dir "$HOME/.agent"
link_file "$DOTFILES_DIR/configs/AGENTS.md" "$HOME/.agent/AGENTS.md"

# Claude Code
# NOTE: MCP servers are NOT registered via symlinking a file. Claude Code stores
# user-scope MCP entries in ~/.claude.json (managed via `claude mcp add`), not in
# ~/.claude/.mcp.json. Registration is handled by scripts/claude.sh which reads
# configs/mcp.json (single source of truth) and runs `claude mcp add-json`.
ensure_dir "$HOME/.claude/hooks" "$HOME/.claude/plugins" "$HOME/.claude/commands" "$HOME/.claude/agents"
link_file "$DOTFILES_DIR/configs/claude-settings.json" "$HOME/.claude/settings.json"
link_file "$DOTFILES_DIR/configs/CLAUDE.md"            "$HOME/.claude/CLAUDE.md"
link_file "$DOTFILES_DIR/configs/RTK.md"               "$HOME/.claude/RTK.md"
link_file "$DOTFILES_DIR/configs/hooks/pretool-guard.sh" "$HOME/.claude/hooks/pretool-guard.sh"
link_file "$DOTFILES_DIR/configs/hooks/skill-md-edit-warn.sh" "$HOME/.claude/hooks/skill-md-edit-warn.sh"
link_file "$DOTFILES_DIR/configs/hooks/work-scope-guard.sh" "$HOME/.claude/hooks/work-scope-guard.sh"
link_file "$DOTFILES_DIR/configs/hooks/context-check.sh" "$HOME/.claude/hooks/context-check.sh"
link_file "$DOTFILES_DIR/configs/agents/scout.md"     "$HOME/.claude/agents/scout.md"
link_file "$DOTFILES_DIR/configs/agents/critic.md"    "$HOME/.claude/agents/critic.md"
link_file "$DOTFILES_DIR/configs/agents/debugger.md"  "$HOME/.claude/agents/debugger.md"
link_file "$DOTFILES_DIR/configs/agents/test-engineer.md" "$HOME/.claude/agents/test-engineer.md"
link_file "$DOTFILES_DIR/configs/agents/security-reviewer.md" "$HOME/.claude/agents/security-reviewer.md"
link_file "$DOTFILES_DIR/configs/agents/git-master.md" "$HOME/.claude/agents/git-master.md"

# Cursor
ensure_dir "$HOME/.cursor/rules"
link_file "$DOTFILES_DIR/configs/AGENTS.md" "$HOME/.cursor/rules/AGENTS.md"

# Codex CLI
ensure_dir "$HOME/.codex"
# Codex config is a mutable local file. scripts/codex.sh copies the portable
# template and preserves machine-local project/plugin/hook state; do not symlink
# it or Codex/Headroom runtime writes can dirty this repo.

RTK_CONFIG_DIR="$HOME/Library/Application Support/rtk"
ensure_dir "$RTK_CONFIG_DIR"
link_file "$DOTFILES_DIR/configs/rtk-config.toml"     "$RTK_CONFIG_DIR/config.toml"

# ── 7. Claude Code ──
info "7/12 Setting up Claude Code..."
bash "$DOTFILES_DIR/scripts/claude.sh"

# ── 8. Codex CLI ──
info "8/12 Setting up Codex CLI..."
bash "$DOTFILES_DIR/scripts/codex.sh"

# ── 9. Hermes Agent ──
info "9/12 Setting up Hermes Agent..."
bash "$DOTFILES_DIR/scripts/hermes.sh"

# ── 10. Tailscale + Tailscale SSH ──
info "10/12 Setting up Tailscale (incl. Tailscale SSH)..."
bash "$DOTFILES_DIR/scripts/tailscale.sh"

# ── 11. purplemux + code-server services ──
info "11/12 Configuring purplemux + code-server services..."
bash "$DOTFILES_DIR/scripts/services.sh"

# ── 회사용 overlay (옵션, git submodule) ──
# company/ 는 git submodule로 별도의 사내 git 저장소에 호스팅된다.
# 새 머신: git clone --recurse-submodules ... 또는 git submodule update --init
info "12/12 Applying company overlay (if available)..."
if [ -x "$DOTFILES_DIR/company/install.sh" ]; then
  echo ""
  info "Detected company/install.sh — running company overlay..."
  bash "$DOTFILES_DIR/company/install.sh"
elif [ -f "$HOME/.company.secrets.env" ]; then
  echo ""
  # shellcheck disable=SC2088  # ~/.company.secrets.env is display text, not a path to expand
  warn "~/.company.secrets.env present but company/ submodule is not initialized."
  warn "Run: git -C $DOTFILES_DIR submodule update --init"
  warn "(Requires SSH access to the internal git host — see company/README.md)"
fi

echo ""
info "Done."
info "Restart your terminal or run 'source ~/.zshrc'."

# ── Manual one-time login flows (interactive — surface clear instructions) ──
echo ""
warn "=== One-time login flows for social-platform CLIs ==="
warn "These open a browser to capture cookies — run them once after install:"
if command -v twitter &>/dev/null && [ ! -f "$HOME/.config/twitter-cli/cookies.json" ] && [ ! -f "$HOME/.twitter-cli/cookies.json" ]; then
  warn "  twitter      # X/Twitter reads browser cookies; make sure you're logged in to x.com in Chrome/Firefox"
else
  info "  twitter      # (already has cookies available or not installed)"
fi
if command -v rdt &>/dev/null && [ ! -f "$HOME/.config/rdt-cli/cookies.json" ] && [ ! -f "$HOME/.rdt-cli/cookies.json" ]; then
  warn "  rdt login    # Reddit cookie capture (required since 2024)"
else
  info "  rdt login    # (already logged in or not installed)"
fi
warn "yt-dlp needs no login; Jina Reader and defuddle need no login by default."
info ""
info "=== Optional API keys (~/.dev.secrets.env) ==="
info "  Exa MCP currently runs anonymously via the hosted endpoint —"
info "  no key needed. If you hit the free-plan rate limit (HTTP 429),"
info "  get a key at https://dashboard.exa.ai/ and re-register the server"
info "  with a header: claude mcp add --transport http -H 'x-api-key: ...' exa https://mcp.exa.ai/mcp"
info "  GitHub Operations on the public dotfiles use 'gh' CLI directly."
info "  The company overlay (if active) adds GitHub MCP servers — see company/AGENTS-company.md."
info ""
info "=== gh CLI authentication ==="
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  info "  gh: github.com authenticated ✓"
else
  info "  See step 2 in the 'REQUIRED MANUAL STEPS' block printed by scripts/git.sh"
  info "  (includes correct scopes for ssh-key add + ssh signing key)."
fi
