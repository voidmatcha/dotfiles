#!/bin/bash
set -euo pipefail
TAG="codex"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

info "Setting up Codex CLI + oh-my-codex (omx)..."

CODEX_CONFIG_DIR="${CODEX_HOME:-$HOME/.codex}"
CODEX_SHARED_CONFIG="$DOTFILES_DIR/configs/codex/config.toml"
CODEX_CMUX_SKILL_REPO="https://github.com/manaflow-ai/cmux.git"
CODEX_CMUX_SKILL_PATH="skills/cmux"

sanitize_codex_shared_config() {
  local config_file="$CODEX_SHARED_CONFIG"
  [ -f "$config_file" ] || return 0

  local tmp_file
  tmp_file=$(mktemp)
  awk '
    BEGIN {
      dynamic_notify = "notify = [\"env\", \"-u\", \"LC_ALL\", \"-u\", \"LC_CTYPE\", \"bash\", \"-lc\", \"exec node \\\"$(npm root -g)/oh-my-codex/dist/scripts/notify-hook.js\\\" \\\"$@\\\"\", \"omx-notify\"]"
    }
    /^notify = .*oh-my-codex.*notify-(hook|dispatcher)\.js/ {
      print dynamic_notify
      next
    }
    # Machine-local state sections — must never live in the shared template.
    # Keep in sync with extract_machine_local_codex_sections below.
    /^\[/ {
      drop = ($0 ~ /^\[projects\."/ || $0 ~ /^\[marketplaces\./ || $0 ~ /^\[plugins\./ || $0 ~ /^\[hooks\.state/)
    }
    !drop { print }
  ' "$config_file" > "$tmp_file"

  if cmp -s "$tmp_file" "$config_file"; then
    rm -f "$tmp_file"
  else
    mv "$tmp_file" "$config_file"
    info "Removed machine-local Codex entries from shared config"
  fi
}

# Codex CLI uses config.toml as a mutable state store on top of user config:
# `codex plugin add` records [plugins."name@marketplace"], marketplace
# registration writes [marketplaces.*], project trust writes [projects."..."],
# and the one-time hook-trust prompt records [hooks.state.*] hashes. Those
# sections are machine-local by definition and must survive template
# refreshes — a plain template copy silently uninstalls every CLI-added
# plugin (e.g. ui-clone-skills@local, registered by the upstream installer
# that claude.sh runs earlier in the same pipeline) and re-triggers every
# hook-trust prompt.
extract_machine_local_codex_sections() {
  local config_file="$1"
  [ -f "$config_file" ] || return 0

  awk '
    # Keep in sync with the drop patterns in sanitize_codex_shared_config.
    /^\[/ {
      keep = ($0 ~ /^\[projects\."/ || $0 ~ /^\[marketplaces\./ || $0 ~ /^\[plugins\./ || $0 ~ /^\[hooks\.state/)
    }
    keep { print }
  ' "$config_file"
}

install_codex_config() {
  local dst="$CODEX_CONFIG_DIR/config.toml"
  local backup_dst tmp_file preserved=""

  ensure_dir "$CODEX_CONFIG_DIR"

  if $DRY_RUN; then
    info "[dry-run] cp $CODEX_SHARED_CONFIG -> $dst (preserving machine-local sections)"
    return 0
  fi

  tmp_file=$(mktemp)
  cp "$CODEX_SHARED_CONFIG" "$tmp_file"

  if [ -L "$dst" ]; then
    rm "$dst"
  elif [ -e "$dst" ]; then
    preserved="$(extract_machine_local_codex_sections "$dst")"
    if [ -n "$preserved" ]; then
      printf '\n%s\n' "$preserved" >> "$tmp_file"
    fi
    if cmp -s "$tmp_file" "$dst"; then
      rm -f "$tmp_file"
      return 0
    fi
    if grep -q "portable template" "$dst"; then
      warn "Refreshing managed Codex config at $dst"
    else
      backup_dst="$(next_backup_path "$dst")"
      warn "Backing up $dst -> $backup_dst"
      mv "$dst" "$backup_dst"
    fi
  fi

  # cat instead of mv: keeps the destination inode and mode stable.
  cat "$tmp_file" > "$dst"
  rm -f "$tmp_file"
  if [ -n "$preserved" ]; then
    info "Installed Codex config: $dst (template + preserved machine-local sections)"
  else
    info "Copied: $CODEX_SHARED_CONFIG -> $dst"
  fi
}

install_codex_cmux_skill() {
  local skills_dir="$CODEX_CONFIG_DIR/skills"
  local dest="$skills_dir/cmux"
  local tmp_dir

  if $DRY_RUN; then
    info "[dry-run] install Codex cmux skill from $CODEX_CMUX_SKILL_REPO:$CODEX_CMUX_SKILL_PATH -> $dest"
    return 0
  fi

  if ! command -v git &>/dev/null; then
    warn "git not found; skipping Codex cmux skill install"
    return 0
  fi

  ensure_dir "$skills_dir"
  tmp_dir="$(mktemp -d)"

  if ! git clone --quiet --depth 1 --filter=blob:none --sparse "$CODEX_CMUX_SKILL_REPO" "$tmp_dir"; then
    rm -rf "$tmp_dir"
    warn "Failed to clone cmux repo; skipping Codex cmux skill install"
    return 0
  fi

  if ! git -C "$tmp_dir" sparse-checkout set "$CODEX_CMUX_SKILL_PATH" >/dev/null 2>&1; then
    rm -rf "$tmp_dir"
    warn "Failed to check out $CODEX_CMUX_SKILL_PATH; skipping Codex cmux skill install"
    return 0
  fi

  if [ ! -f "$tmp_dir/$CODEX_CMUX_SKILL_PATH/SKILL.md" ]; then
    rm -rf "$tmp_dir"
    warn "cmux skill missing SKILL.md upstream; skipping Codex cmux skill install"
    return 0
  fi

  if [ -e "$dest" ]; then
    rm -rf "$dest"
  fi

  cp -R "$tmp_dir/$CODEX_CMUX_SKILL_PATH" "$dest"
  rm -rf "$tmp_dir"
  info "Installed Codex cmux skill -> $dest"
}

if ! $DRY_RUN; then
  sanitize_codex_shared_config
fi
install_codex_config

if $DRY_RUN; then
  if command -v codex &>/dev/null; then
    info "[dry-run] codex --version"
  else
    info "[dry-run] npm install -g @openai/codex oh-my-codex"
  fi
  if command -v omx &>/dev/null; then
    info "[dry-run] omx --version"
  else
    info "[dry-run] omx not installed — would install with oh-my-codex"
  fi
  install_codex_cmux_skill
  if [ -x "$DOTFILES_DIR/scripts/skills.sh" ]; then
    bash "$DOTFILES_DIR/scripts/skills.sh" codex
  fi
  info "[dry-run] codex login status"
  info "[dry-run] omx setup / omx doctor are manual post-install checks"
  info "Codex CLI + oh-my-codex setup done"
  exit 0
fi

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

install_codex_cmux_skill
if [ -x "$DOTFILES_DIR/scripts/skills.sh" ]; then
  bash "$DOTFILES_DIR/scripts/skills.sh" codex
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

sanitize_codex_shared_config

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
  warn "       bash $DOTFILES_DIR/scripts/codex.sh  # normalize machine-local paths afterwards"
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
