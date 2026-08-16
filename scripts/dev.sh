#!/bin/bash
set -euo pipefail
TAG="dev"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── nvm + Node.js ──
info "Installing nvm..."
if [ -d "$HOME/.nvm" ]; then
  info "nvm already installed"
else
  if $DRY_RUN; then
    info "[dry-run] Skipping nvm install"
  else
    NVM_VERSION=$(curl -fsSL https://api.github.com/repos/nvm-sh/nvm/releases/latest 2>/dev/null | grep '"tag_name"' | cut -d'"' -f4 || true)
    NVM_VERSION="${NVM_VERSION:-v0.40.5}"
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
  # set +u: SDKMAN references unset variables internally (ZSH_VERSION, SDKMAN_CANDIDATES_CACHE, etc.)
  set +u
  # shellcheck source=/dev/null
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
# Check both: pyenv on PATH OR ~/.pyenv directory present (PATH might not be
# loaded yet in this non-interactive shell, but the install would still be there).
if command -v pyenv &>/dev/null || [ -x "$HOME/.pyenv/bin/pyenv" ]; then
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

  # Stale `.pyenv-shim` is left behind when a previous `pyenv rehash` was
  # interrupted; the next rehash can't overwrite it and spins for 60s before
  # failing. Must remove BEFORE `pyenv init -` because init triggers rehash.
  rm -f "$PYENV_ROOT/shims/.pyenv-shim"

  eval "$(pyenv init -)" || warn "pyenv init failed — check manually"

  LATEST_PYTHON=$(pyenv install --list | grep -E '^\s+3\.[0-9]+\.[0-9]+$' | tail -1 | tr -d ' ' || true)
  info "Installing Python $LATEST_PYTHON..."
  pyenv install -s "$LATEST_PYTHON" || warn "pyenv install $LATEST_PYTHON failed — check manually"
  pyenv global "$LATEST_PYTHON" || warn "pyenv global $LATEST_PYTHON failed — check manually"
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

# ── serena (MCP server: semantic code search + editing) ──
info "Checking serena..."
if $DRY_RUN; then
  info "[dry-run] uv tool install serena-agent@latest && serena init"
elif ! command -v uv &>/dev/null; then
  warn "uv not installed — skipping serena (run brew bundle first)"
else
  if ! command -v serena &>/dev/null; then
    info "Installing serena via uv..."
    if ! uv tool install -p 3.13 serena-agent@latest --prerelease=allow; then
      warn "serena install failed — try manually: uv tool install -p 3.13 serena-agent@latest --prerelease=allow"
    fi
  else
    info "serena already installed"
  fi

  # serena init is idempotent; safe to re-run on existing setups.
  # 120s timeout: first run can stall on LSP backend downloads.
  if command -v serena &>/dev/null; then
    info "Initialising serena (language server backend)..."
    if ! with_timeout 120 serena init </dev/null; then
      warn "serena init failed or timed out — run manually with: serena init"
    fi
  fi
fi

# ── graphify (Claude/Codex skill: knowledge graph from any folder) ──
info "Checking graphify..."
install_graphify_platforms() {
  local platform
  for platform in claude codex; do
    if graphify install --platform "$platform"; then
      info "graphify skill installed for $platform — use /graphify for mixed docs/PDFs"
    else
      warn "graphify install for $platform failed — try: graphify install --platform $platform"
    fi
  done
}

if $DRY_RUN; then
  info "[dry-run] python3 -m pip install --user graphifyy && graphify install --platform claude && graphify install --platform codex"
else
  if command -v graphify &>/dev/null; then
    info "graphify already installed"
  else
    info "Installing graphify (python3 user site)..."
    # graphify ships under "graphifyy" on PyPI until the "graphify" name is reclaimed
    if ! python3 -m pip install --user graphifyy 2>/dev/null || ! command -v graphify &>/dev/null; then
      warn "graphify install failed — try manually: python3 -m pip install --user graphifyy && graphify install --platform claude && graphify install --platform codex"
    fi
  fi

  if command -v graphify &>/dev/null; then
    install_graphify_platforms
  fi
fi

# ── defuddle (clean web page extraction) ──
info "Checking defuddle..."
if $DRY_RUN; then
  info "[dry-run] npm install -g defuddle"
else
  if ! command -v defuddle &>/dev/null; then
    info "Installing defuddle (global)"
    npm install -g defuddle 2>/dev/null || info "⚠️  defuddle install failed — check manually"
  else
    info "defuddle already installed"
  fi
fi

# ── codegraph (pre-indexed code knowledge graph MCP for Claude/Codex) ──
# Read-only complement to serena. Per-project SQLite index built by tree-sitter;
# zero-config, watcher auto-syncs on save. Personal user-scope only — not in
# NAVER MCP catalog, so excluded from ~/work/.mcp.json (company project scope).
info "Checking codegraph..."
if $DRY_RUN; then
  info "[dry-run] npm install -g @colbymchenry/codegraph"
else
  if ! command -v codegraph &>/dev/null; then
    info "Installing codegraph (global)"
    npm install -g @colbymchenry/codegraph 2>/dev/null || info "⚠️  codegraph install failed — check manually"
  else
    info "codegraph already installed ($(codegraph --version 2>/dev/null || echo unknown))"
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
# `rtk init --global` registers the in-place hook (settings.json calls
# `rtk hook claude` directly instead of a wrapper script under
# ~/.claude/hooks/). claude-settings.json reflects that.
info "Checking rtk hook setup..."
if $DRY_RUN; then
  info "[dry-run] Skipping rtk init --global"
elif command -v rtk &>/dev/null; then
  if rtk init --global; then
    info "rtk hook registered (restart Claude Code to activate)"
  else
    warn "rtk init failed — Claude Code will run without RTK compression; not blocking install"
  fi
else
  warn "rtk not installed (brew bundle should have it) — skipping"
fi

# ── agent statusline helpers ──
# Claude's statusLine is command-based, so a small wrapper can prepend the
# current cmux/tmux/session label while delegating to the existing HUD.
# Codex status_line is config.toml-based; omit thread-title to avoid UUID fallback in HUD.
if [ -x "$DOTFILES_DIR/scripts/statusline.sh" ]; then
  bash "$DOTFILES_DIR/scripts/statusline.sh"
fi

# ── code-server browser IDE extensions ──
if [ -x "$DOTFILES_DIR/scripts/code-server.sh" ]; then
  bash "$DOTFILES_DIR/scripts/code-server.sh"
fi

# ── agent-browser (Vercel Labs) ──
info "Checking agent-browser..."
if $DRY_RUN; then
  info "[dry-run] Skipping agent-browser install"
else
  # Check both PATH and the install location (~/.local/bin may not be on
  # PATH yet during install.sh execution).
  if command -v agent-browser &>/dev/null || [ -x "$HOME/.local/bin/agent-browser" ]; then
    info "agent-browser already installed"
  else
    info "Installing agent-browser..."
    mkdir -p "$HOME/.local/bin"
    ARCH="$(uname -m)"
    if [ "$ARCH" = "arm64" ]; then
      ASSET="agent-browser-darwin-arm64"
    else
      ASSET="agent-browser-darwin-x64"
    fi
    LATEST_URL="$(curl -fsSL https://api.github.com/repos/vercel-labs/agent-browser/releases/latest 2>/dev/null \
      | grep "browser_download_url" | grep "$ASSET\"" | head -1 | cut -d'"' -f4)"
    if [ -z "$LATEST_URL" ]; then
      warn "agent-browser: failed to resolve release URL (GitHub API rate-limit or asset rename?) — install manually"
    elif curl -fsSL "$LATEST_URL" -o "$HOME/.local/bin/agent-browser" && chmod +x "$HOME/.local/bin/agent-browser"; then
      info "agent-browser installed ($LATEST_URL)"
    else
      warn "agent-browser: download failed from $LATEST_URL — install manually"
      rm -f "$HOME/.local/bin/agent-browser"
    fi
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

# ── feedparser (RSS/Atom parser, Python lib used inline by agents) ──
info "Checking feedparser..."
if $DRY_RUN; then
  info "[dry-run] python3 -m pip install --user feedparser"
elif python3 -c "import feedparser" 2>/dev/null; then
  info "feedparser already installed"
else
  python3 -m pip install --user feedparser 2>/dev/null || warn "feedparser install failed — try: python3 -m pip install --user feedparser"
fi

# ── PyYAML (Codex plugin validator dependency) ──
info "Checking PyYAML..."
if $DRY_RUN; then
  info "[dry-run] python3 -m pip install --user PyYAML"
elif python3 -c "import yaml" 2>/dev/null; then
  info "PyYAML already installed"
else
  python3 -m pip install --user PyYAML 2>/dev/null || warn "PyYAML install failed — try: python3 -m pip install --user PyYAML"
fi

# ── Social-platform read tools (Agent-Reach upstream tools) ──
# Install the upstream CLIs directly. See README.md for the one-liners
# agents should call.
# - yt-dlp: YouTube/Bilibili/1800+ sites — installed via Brewfile (no auth)
# - twitter-cli (public-clis/twitter-cli): X/Twitter via cookie auth — `twitter search/tweet/user`
# - rdt-cli (public-clis/rdt-cli): Reddit via cookie auth — `rdt search/read`
for tool_pkg in "twitter-cli" "rdt-cli"; do
  case "$tool_pkg" in
    twitter-cli) cli="twitter" ;;
    rdt-cli)     cli="rdt"     ;;
  esac
  info "Checking $cli ($tool_pkg)..."
  if $DRY_RUN; then
    info "[dry-run] pipx install $tool_pkg"
  elif command -v "$cli" &>/dev/null; then
    info "$cli already installed"
  elif command -v pipx &>/dev/null; then
    pipx install "$tool_pkg" 2>/dev/null || warn "$tool_pkg install failed — try: pipx install $tool_pkg"
  else
    warn "pipx not installed — skipping $tool_pkg. Install pipx first (brew install pipx)"
  fi
done

# Initial cookie-login flow — interactive, must be run by the user manually.
# We surface a clear reminder rather than blocking install.sh.
if ! $DRY_RUN; then
  if command -v twitter &>/dev/null && [ ! -f "$HOME/.config/twitter-cli/cookies.json" ] && [ ! -f "$HOME/.twitter-cli/cookies.json" ]; then
    warn "twitter (twitter-cli) installed — uses browser cookie automatically; ensure you're logged in to x.com in Chrome/Firefox"
  fi
  if command -v rdt &>/dev/null && [ ! -f "$HOME/.config/rdt-cli/cookies.json" ] && [ ! -f "$HOME/.rdt-cli/cookies.json" ]; then
    warn "rdt (rdt-cli) installed but not logged in — run: rdt login   (opens browser to capture reddit cookie)"
  fi
fi

# ── wrangler (Cloudflare Workers/Pages/R2/D1 CLI) ──
info "Checking wrangler..."
if $DRY_RUN; then
  info "[dry-run] Skipping wrangler install"
else
  if ! command -v wrangler &>/dev/null; then
    info "Installing wrangler (global)"
    npm install -g wrangler 2>/dev/null || info "⚠️  wrangler install failed — check manually"
  else
    info "wrangler already installed"
  fi
fi

info "Dev environment setup done"
