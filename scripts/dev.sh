#!/bin/bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-false}"

GREEN='\033[0;32m'
NC='\033[0m'
info() { echo -e "${GREEN}[dev]${NC} $1"; }

# ── nvm + Node.js ──
info "Installing nvm..."
if [ -d "$HOME/.nvm" ]; then
  info "nvm already installed"
else
  if $DRY_RUN; then
    info "[dry-run] Skipping nvm install"
  else
    NVM_VERSION=$(curl -fsSL https://api.github.com/repos/nvm-sh/nvm/releases/latest | grep '"tag_name"' | cut -d'"' -f4)
    curl -o- "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" | bash
  fi
fi

if ! $DRY_RUN; then
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

  info "Installing Node.js LTS..."
  nvm install --lts
  nvm alias default lts/*

  info "Enabling corepack (pnpm + yarn)..."
  corepack enable
  corepack prepare pnpm@latest --activate
  corepack prepare yarn@stable --activate
else
  info "[dry-run] Skipping Node.js LTS install"
  info "[dry-run] Skipping corepack (pnpm + yarn)"
fi

# ── SDKMAN + Java + Maven ──
info "Installing SDKMAN..."
if [ -d "$HOME/.sdkman" ]; then
  info "SDKMAN already installed"
else
  if $DRY_RUN; then
    info "[dry-run] Skipping SDKMAN install"
  else
    curl -s "https://get.sdkman.io" | bash
  fi
fi

if ! $DRY_RUN; then
  export SDKMAN_DIR="$HOME/.sdkman"
  # shellcheck source=/dev/null
  # set +u: SDKMAN references unset variables internally (ZSH_VERSION, SDKMAN_CANDIDATES_CACHE, etc.)
  set +u
  [[ -s "$SDKMAN_DIR/bin/sdkman-init.sh" ]] && source "$SDKMAN_DIR/bin/sdkman-init.sh"

  info "Installing Java LTS..."
  sdk install java < /dev/null 2>/dev/null || info "⚠️  Java install failed — check manually"

  info "Installing Maven..."
  sdk install maven < /dev/null 2>/dev/null || info "⚠️  Maven install failed — check manually"
  set -u
else
  info "[dry-run] Skipping Java + Maven install"
fi

# ── pyenv + Python ──
info "Installing pyenv..."
if command -v pyenv &>/dev/null; then
  info "pyenv already installed"
else
  if $DRY_RUN; then
    info "[dry-run] Skipping pyenv install"
  else
    curl https://pyenv.run | bash
  fi
fi

if ! $DRY_RUN; then
  export PYENV_ROOT="$HOME/.pyenv"
  export PATH="$PYENV_ROOT/bin:$PATH"
  eval "$(pyenv init -)"

  LATEST_PYTHON=$(pyenv install --list | grep -E '^\s+3\.[0-9]+\.[0-9]+$' | tail -1 | tr -d ' ')
  info "Installing Python $LATEST_PYTHON..."
  pyenv install -s "$LATEST_PYTHON"
  pyenv global "$LATEST_PYTHON"
else
  info "[dry-run] Skipping latest Python install"
fi

# ── Playwright CLI (for coding agents) ──
info "Installing Playwright CLI..."
if $DRY_RUN; then
  info "[dry-run] Skipping Playwright CLI install"
else
  if ! command -v playwright-cli &>/dev/null; then
    info "Installing Playwright CLI (global)"
    npm install -g @playwright/cli@latest 2>/dev/null || info "⚠️  Playwright CLI install failed — check manually"
  else
    info "Playwright CLI already installed"
  fi
fi

# ── whisper-cpp model download ──
WHISPER_MODELS_DIR="$HOME/.whisper/models"
info "Checking whisper-cpp model..."
if $DRY_RUN; then
  info "[dry-run] Skipping whisper-cpp model download"
else
  mkdir -p "$WHISPER_MODELS_DIR"
  if [ ! -f "$WHISPER_MODELS_DIR/ggml-large-v3-turbo.bin" ]; then
    info "Downloading whisper-cpp large-v3-turbo model (~1.5GB)..."
    curl -L -o "$WHISPER_MODELS_DIR/ggml-large-v3-turbo.bin" \
      "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
  else
    info "whisper-cpp model already exists"
  fi
fi

# ── ccusage (Claude Code usage dashboard) ──
info "Checking ccusage..."
if $DRY_RUN; then
  info "[dry-run] Skipping ccusage install"
else
  if ! command -v ccusage &>/dev/null; then
    info "Installing ccusage (global)"
    npm install -g ccusage 2>/dev/null || info "⚠️  ccusage install failed — check manually"
  else
    info "ccusage already installed"
  fi
fi

# ── rtk (Claude Code hook for LLM token savings) ──
info "Checking rtk hook setup..."
if $DRY_RUN; then
  info "[dry-run] Skipping rtk init --global"
else
  if command -v rtk &>/dev/null; then
    rtk init --global 2>/dev/null && info "rtk hook registered (restart Claude Code to activate)" || info "⚠️  rtk init failed — check manually"
  else
    info "⚠️  rtk not installed — run brew bundle first"
  fi
fi

# ── agent-browser (Vercel Labs) ──
info "Checking agent-browser..."
if $DRY_RUN; then
  info "[dry-run] Skipping agent-browser install"
else
  if ! command -v agent-browser &>/dev/null; then
    info "Installing agent-browser..."
    mkdir -p "$HOME/.local/bin"
    ARCH="$(uname -m)"
    if [ "$ARCH" = "arm64" ]; then
      ASSET="agent-browser-darwin-arm64"
    else
      ASSET="agent-browser-darwin-x64"
    fi
    LATEST_URL="$(curl -s https://api.github.com/repos/vercel-labs/agent-browser/releases/latest \
      | grep "browser_download_url" | grep "$ASSET\"" | head -1 | cut -d'"' -f4)"
    curl -fsSL "$LATEST_URL" -o "$HOME/.local/bin/agent-browser"
    chmod +x "$HOME/.local/bin/agent-browser"
    info "agent-browser installed"
  else
    info "agent-browser already installed"
  fi
fi

# ── portless (port management) ──
info "Checking portless..."
if $DRY_RUN; then
  info "[dry-run] Skipping portless install"
else
  if ! command -v portless &>/dev/null; then
    info "Installing portless (global)"
    npm install -g portless 2>/dev/null || info "⚠️  portless install failed — check manually"
  else
    info "portless already installed"
  fi
fi

info "Dev environment setup done"
