#!/bin/bash
set -euo pipefail
TAG="dev"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# ── nvm + Node.js ──
info "Installing nvm..."
install_nvm_latest() {
  local allow_fallback="$1"
  local nvm_version installer

  if $DRY_RUN; then
    info "[dry-run] install/update nvm from its latest GitHub release"
    return 0
  fi

  nvm_version="$(curl -fsSL https://api.github.com/repos/nvm-sh/nvm/releases/latest 2>/dev/null \
    | grep '"tag_name"' | cut -d'"' -f4 || true)"
  if [ -z "$nvm_version" ]; then
    if $allow_fallback; then
      nvm_version="v0.40.5"
      warn "nvm latest release lookup failed — using bootstrap fallback $nvm_version"
    else
      warn "nvm latest release lookup failed — keeping the installed version"
      return 1
    fi
  fi

  installer="$(mktemp)"
  if curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/${nvm_version}/install.sh" -o "$installer" \
      && NVM_VERSION="$nvm_version" bash "$installer"; then
    info "nvm converged to $nvm_version"
  else
    rm -f "$installer"
    warn "nvm install/update failed — continuing with the installed version"
    return 1
  fi
  rm -f "$installer"
}

if [ -d "$HOME/.nvm" ]; then
  info "nvm already installed"
  if $UPGRADE; then
    install_nvm_latest false || true
  fi
else
  install_nvm_latest true || true
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
  if $DRY_RUN && $UPGRADE; then
    info "[dry-run] sdk selfupdate force"
  fi
else
  if $DRY_RUN; then
    info "[dry-run] Skipping SDKMAN install"
  else
    curl -s "https://get.sdkman.io" | bash
  fi
fi

if ! $DRY_RUN; then
  if $UPGRADE; then
    info "Updating SDKMAN..."
    run_sdkman selfupdate force < /dev/null \
      || warn "SDKMAN self-update failed — continuing with the installed version"
  fi

  info "Installing Java LTS..."
  run_sdkman install java < /dev/null 2>/dev/null || info "⚠️  Java install failed — check manually"

  info "Installing Maven..."
  run_sdkman install maven < /dev/null 2>/dev/null || info "⚠️  Maven install failed — check manually"
else
  info "[dry-run] Skipping Java + Maven install"
fi

# ── pyenv + Python ──
info "Installing pyenv..."
# Check both: pyenv on PATH OR ~/.pyenv directory present (PATH might not be
# loaded yet in this non-interactive shell, but the install would still be there).
if command -v pyenv &>/dev/null || [ -x "$HOME/.pyenv/bin/pyenv" ]; then
  info "pyenv already installed"
  $UPGRADE && git_pull_if_clean "$HOME/.pyenv"
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
ensure_npm_global_latest "@playwright/cli" "playwright-cli" \
  || warn "Playwright CLI install/update failed — check manually"

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
  if $UPGRADE; then
    info "[dry-run] uv tool upgrade serena-agent --prerelease=allow && serena init"
  else
    info "[dry-run] uv tool install serena-agent@latest if missing && serena init"
  fi
elif ! command -v uv &>/dev/null; then
  warn "uv not installed — skipping serena (run brew bundle first)"
else
  if ! command -v serena &>/dev/null; then
    info "Installing serena via uv..."
    if ! uv tool install -p 3.13 serena-agent@latest --prerelease=allow; then
      warn "serena install failed — try manually: uv tool install -p 3.13 serena-agent@latest --prerelease=allow"
    fi
  elif $UPGRADE; then
    info "Ensuring serena is at the latest release..."
    uv tool upgrade serena-agent --prerelease=allow \
      || warn "serena update failed — continuing with the installed version"
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

# ── defuddle (clean web page extraction) ──
info "Checking defuddle..."
ensure_npm_global_latest "defuddle" "defuddle" \
  || warn "defuddle install/update failed — check manually"

# ── codegraph (pre-indexed code knowledge graph MCP for Claude/Codex) ──
# Read-only complement to serena. Per-project SQLite index built by tree-sitter;
# zero-config, watcher auto-syncs on save. Personal user-scope only — not in
# NAVER MCP catalog, so excluded from ~/work/.mcp.json (company project scope).
info "Checking codegraph..."
ensure_npm_global_latest "@colbymchenry/codegraph" "codegraph" \
  || warn "codegraph install/update failed — check manually"

# ── ccusage (Claude Code usage dashboard) ──
info "Checking ccusage..."
ensure_npm_global_latest "ccusage" "ccusage" \
  || warn "ccusage install/update failed — check manually"

# ── rtk (Claude Code hook for LLM token savings) ──
# `rtk init --global --hook-only` registers the in-place hook without appending
# an @RTK.md import to the always-loaded CLAUDE.md (settings.json calls
# `rtk hook claude` directly instead of a wrapper script under
# ~/.claude/hooks/). claude-settings.json reflects that.
info "Checking rtk hook setup..."
if $DRY_RUN; then
  info "[dry-run] Skipping rtk init --global --hook-only"
elif command -v rtk &>/dev/null; then
  if rtk init --global --hook-only; then
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
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
  AGENT_BROWSER_ASSET="agent-browser-darwin-arm64"
else
  AGENT_BROWSER_ASSET="agent-browser-darwin-x64"
fi
ensure_github_release_binary_latest \
  "vercel-labs/agent-browser" "$AGENT_BROWSER_ASSET" \
  "$HOME/.local/bin/agent-browser" "agent-browser" \
  || warn "agent-browser install/update failed — continuing with the installed version"

# ── portless (port management) ──
info "Checking portless..."
ensure_npm_global_latest "portless" "portless" \
  || warn "portless install/update failed — check manually"

# ── feedparser (RSS/Atom parser, Python lib used inline by agents) ──
info "Checking feedparser..."
if $DRY_RUN; then
  if $UPGRADE; then
    info "[dry-run] python3 -m pip install --user --upgrade feedparser"
  else
    info "[dry-run] python3 -m pip install --user feedparser if missing"
  fi
elif python3 -c "import feedparser" 2>/dev/null && ! $UPGRADE; then
  info "feedparser already installed"
else
  pip_args=(install --user)
  $UPGRADE && pip_args+=(--upgrade)
  python3 -m pip "${pip_args[@]}" feedparser 2>/dev/null || warn "feedparser install/update failed"
fi

# ── PyYAML (Codex plugin validator dependency) ──
info "Checking PyYAML..."
if $DRY_RUN; then
  if $UPGRADE; then
    info "[dry-run] python3 -m pip install --user --upgrade PyYAML"
  else
    info "[dry-run] python3 -m pip install --user PyYAML if missing"
  fi
elif python3 -c "import yaml" 2>/dev/null && ! $UPGRADE; then
  info "PyYAML already installed"
else
  pip_args=(install --user)
  $UPGRADE && pip_args+=(--upgrade)
  python3 -m pip "${pip_args[@]}" PyYAML 2>/dev/null || warn "PyYAML install/update failed"
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
  ensure_pipx_latest "$tool_pkg" "$cli" \
    || warn "$tool_pkg install/update failed — continuing with the installed version"
done

# Initial browser-login flow — interactive, must be run by the user manually.
# Keep the reminder behind the unified auth entry point rather than teaching
# each provider's storage details here.
if ! $DRY_RUN; then
  if { command -v uvx &>/dev/null && [ ! -d "$HOME/.linkedin-mcp/profile" ]; } || \
     { command -v rdt &>/dev/null && [ ! -f "$HOME/.config/rdt-cli/credential.json" ]; }; then
    warn "Social browser login is incomplete — run: dotfiles-auth setup social"
  fi
fi

# ── wrangler (Cloudflare Workers/Pages/R2/D1 CLI) ──
info "Checking wrangler..."
ensure_npm_global_latest "wrangler" "wrangler" \
  || warn "wrangler install/update failed — check manually"

info "Dev environment setup done"
