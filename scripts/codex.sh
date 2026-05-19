#!/bin/bash
set -euo pipefail
TAG="codex"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

info "Setting up Codex CLI + oh-my-codex (omx)..."

CODEX_CONFIG_DIR="${CODEX_HOME:-$HOME/.codex}"
ensure_dir "$CODEX_CONFIG_DIR"
link_file "$DOTFILES_DIR/configs/codex/config.toml" \
          "$CODEX_CONFIG_DIR/config.toml"

# ── Install Codex CLI + omx ──
# `omx` is Yeachan-Heo/oh-my-codex — a multi-agent orchestration runtime on
# top of the official Codex CLI. README install path:
#   npm install -g @openai/codex oh-my-codex
# `omx doctor` then verifies install shape; `omx setup` provisions native
# agents and prompts (run interactively on first use).
if command -v codex &>/dev/null; then
  CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
  info "Found codex ${CODEX_VERSION}"
  if command -v omx &>/dev/null; then
    OMX_VERSION=$(omx --version 2>/dev/null || echo "unknown")
    info "Found omx ${OMX_VERSION}"
  else
    warn "omx not installed — run 'npm install -g oh-my-codex' to add the orchestration layer"
  fi
elif $DRY_RUN; then
  info "[dry-run] npm install -g @openai/codex oh-my-codex"
else
  if ! command -v npm &>/dev/null; then
    warn "npm not found in PATH"
    warn "Run 'bash $DOTFILES_DIR/scripts/dev.sh' first, or install Codex with Homebrew: brew install --cask codex"
    exit 1
  fi

  if npm install -g @openai/codex oh-my-codex; then
    info "Codex CLI + omx installed"
  else
    warn "npm install -g @openai/codex oh-my-codex failed"
    exit 1
  fi
fi

# ── Codex auth check ──
if command -v codex &>/dev/null; then
  if codex login status >/dev/null 2>&1; then
    info "codex auth already configured"
  else
    echo ""
    warn "codex is not authenticated yet."
    echo ""
    echo "Run 'codex login' for ChatGPT sign-in, or pipe an API key with:"
    echo "  printenv OPENAI_API_KEY | codex login --with-api-key"
    echo "Use 'codex login --device-auth' for a headless device-code flow."
    echo ""

    if $DRY_RUN; then
      info "[dry-run] would run: codex login"
    elif $NON_INTERACTIVE; then
      warn "Non-interactive mode: skipped codex login. Run it manually before first use."
    else
      read -rp "Run 'codex login' now? (Y/n) " run_auth
      if [[ "$run_auth" =~ ^[Nn]$ ]]; then
        warn "Skipped. Run 'codex login' manually before first use."
      else
        codex login || warn "codex login exited non-zero — re-run manually if needed"
      fi
    fi
  fi
elif $DRY_RUN; then
  info "[dry-run] codex login status"
else
  warn "codex is still not available on PATH. Run 'codex login' after installing it."
fi

# ── omx setup / doctor (manual — interactive on first run) ──
# `omx setup` provisions native agents/prompts/hooks; `omx doctor` reports
# install shape. Both are interactive in the upstream, so we surface them
# as REQUIRED MANUAL STEPS rather than running blind.
if command -v omx &>/dev/null && ! $DRY_RUN; then
  echo ""
  warn "═════════════════════════════════════════════════════════════════"
  warn "  omx (oh-my-codex) — REQUIRED MANUAL STEPS after first install"
  warn "═════════════════════════════════════════════════════════════════"
  warn "  1) Provision native agents/prompts/hooks:"
  warn "       omx setup"
  warn "     (re-run after each \`oh-my-codex\` npm version bump, or use \`omx update\`)"
  warn ""
  warn "  2) Verify install shape + runtime prerequisites:"
  warn "       omx doctor"
  warn ""
  warn "  3) Roundtrip smoke test (auth + profile + base-URL):"
  warn "       omx exec --skip-git-repo-check -C . \"Reply with exactly OMX-EXEC-OK\""
  warn ""
  warn "  4) Recommended launch:"
  warn "       omx --madmax --high          # default: managed detached tmux"
  warn "       omx --direct --yolo          # one-off, no OMX tmux/HUD management"
  warn "  Set OMX_LAUNCH_POLICY=direct|tmux|detached-tmux|auto for a persistent default."
  echo ""
fi

info "Codex CLI + oh-my-codex setup done"
