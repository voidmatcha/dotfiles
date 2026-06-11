#!/bin/bash
set -euo pipefail
# shellcheck disable=SC2034 # consumed by scripts/lib/common.sh after source.
TAG="skills"
# shellcheck source=scripts/lib/common.sh
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

CODEX_CONFIG_DIR="${CODEX_HOME:-$HOME/.codex}"
LOCAL_PLUGIN_DIR="$DOTFILES_DIR/plugins/local-skills"
LOCAL_SKILLS_DIR="$LOCAL_PLUGIN_DIR/skills"
CLAUDE_MARKETPLACE_NAME="dotfiles-local"
CLAUDE_PLUGIN_ID="local-skills@$CLAUDE_MARKETPLACE_NAME"
CLAUDE_KNOWN_MARKETPLACES_JSON="$HOME/.claude/plugins/known_marketplaces.json"
CLAUDE_INSTALLED_PLUGINS_JSON="$HOME/.claude/plugins/installed_plugins.json"
MATT_POCOCK_SKILLS_REF="${MATT_POCOCK_SKILLS_REF:-2bf70051928429983de3b5718d277150926f8c89}"
GRILL_ME_SKILL_URL="https://raw.githubusercontent.com/mattpocock/skills/${MATT_POCOCK_SKILLS_REF}/skills/productivity/grill-me/SKILL.md"

usage() {
  cat <<'USAGE'
Usage: scripts/skills.sh [all|claude|codex] [--dry-run]

Installs repo-local skills through the local plugin/skills path and upstream
standalone skills pinned for reproducibility:
  claude  registers this repo as local-skills@dotfiles-local and installs upstream Claude skills
  codex   symlinks plugins/local-skills/skills/* into ~/.codex/skills and installs upstream Codex skills
  all     does both (default)
USAGE
}

mode="all"
while [ "$#" -gt 0 ]; do
  case "$1" in
    all|claude|codex)
      mode="$1"
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      warn "unknown argument: $1"
      usage >&2
      exit 2
      ;;
  esac
  shift
done

install_upstream_skill_from_url() {
  local tool_name="$1"
  local skills_dir="$2"
  local skill_name="$3"
  local url="$4"
  local dest="$skills_dir/$skill_name"
  local tmp_file backup_dst

  if $DRY_RUN; then
    info "[dry-run] install upstream $tool_name skill $skill_name from $url -> $dest"
    return 0
  fi

  ensure_dir "$skills_dir"
  tmp_file="$(mktemp)"
  if ! curl -fsSL "$url" -o "$tmp_file"; then
    rm -f "$tmp_file"
    warn "Failed upstream $tool_name skill download: $skill_name ($url)"
    return 0
  fi

  if ! grep -q '^name: '"$skill_name"'$' "$tmp_file"; then
    rm -f "$tmp_file"
    warn "Downloaded upstream skill has unexpected name; skipping: $skill_name"
    return 0
  fi

  if [ -L "$dest" ]; then
    rm "$dest"
    mkdir -p "$dest"
  elif [ -e "$dest" ] && [ ! -d "$dest" ]; then
    backup_dst="$(next_backup_path "$dest")"
    warn "Backing up $dest -> $backup_dst"
    mv "$dest" "$backup_dst"
    mkdir -p "$dest"
  else
    mkdir -p "$dest"
  fi

  mv "$tmp_file" "$dest/SKILL.md"
  info "Installed upstream $tool_name skill: $skill_name -> $dest"
}

install_claude_upstream_skills() {
  install_upstream_skill_from_url "Claude" "$HOME/.claude/skills" "grill-me" "$GRILL_ME_SKILL_URL"
}

install_codex_upstream_skills() {
  install_upstream_skill_from_url "Codex" "$CODEX_CONFIG_DIR/skills" "grill-me" "$GRILL_ME_SKILL_URL"
}

install_codex_local_skills() {
  local skills_dir="$CODEX_CONFIG_DIR/skills"
  local skill_dir skill_name dest backup_dst

  if [ ! -d "$LOCAL_SKILLS_DIR" ]; then
    warn "local skills directory not found: $LOCAL_SKILLS_DIR"
    return 0
  fi

  ensure_dir "$skills_dir"

  while IFS= read -r skill_dir; do
    [ -f "$skill_dir/SKILL.md" ] || continue
    skill_name="$(basename "$skill_dir")"
    dest="$skills_dir/$skill_name"

    if $DRY_RUN; then
      info "[dry-run] install local Codex skill $skill_name -> $dest"
      continue
    fi

    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
      backup_dst="$(next_backup_path "$dest")"
      warn "Backing up $dest -> $backup_dst"
      mv "$dest" "$backup_dst"
    fi

    if [ -L "$dest" ]; then
      rm "$dest"
    fi

    ln -s "$skill_dir" "$dest"
    info "Installed local Codex skill: $skill_name -> $dest"
  done < <(find "$LOCAL_SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d | sort)
}

install_claude_local_plugin() {
  if [ ! -f "$DOTFILES_DIR/.claude-plugin/marketplace.json" ] || [ ! -f "$LOCAL_PLUGIN_DIR/.claude-plugin/plugin.json" ]; then
    warn "local Claude plugin manifest missing under $DOTFILES_DIR/.claude-plugin or $LOCAL_PLUGIN_DIR/.claude-plugin"
    return 0
  fi

  if $DRY_RUN; then
    info "[dry-run] claude plugin marketplace add $DOTFILES_DIR"
    info "[dry-run] claude plugin install $CLAUDE_PLUGIN_ID"
    return 0
  fi

  if ! command -v claude &>/dev/null; then
    warn "claude not found; skipping local Claude plugin install"
    return 0
  fi

  ensure_dir "$HOME/.claude/plugins"

  # shellcheck disable=SC2016 # jq variables are passed via --arg.
  if json_entry_exists "$CLAUDE_KNOWN_MARKETPLACES_JSON" 'has($n)' --arg n "$CLAUDE_MARKETPLACE_NAME"; then
    info "Local Claude marketplace already registered: $CLAUDE_MARKETPLACE_NAME"
  elif with_timeout 180 claude plugin marketplace add "$DOTFILES_DIR" </dev/null; then
    info "Added local Claude marketplace: $CLAUDE_MARKETPLACE_NAME"
  else
    warn "Failed local Claude marketplace: $CLAUDE_MARKETPLACE_NAME (timeout or error — re-run manually if needed)"
    return 0
  fi

  # shellcheck disable=SC2016 # jq variables are passed via --arg.
  if json_entry_exists "$CLAUDE_INSTALLED_PLUGINS_JSON" '.plugins | has($p)' --arg p "$CLAUDE_PLUGIN_ID"; then
    info "Local Claude plugin already installed: $CLAUDE_PLUGIN_ID"
  elif with_timeout 180 claude plugin install "$CLAUDE_PLUGIN_ID" </dev/null; then
    info "Installed local Claude plugin: $CLAUDE_PLUGIN_ID"
  else
    warn "Failed local Claude plugin: $CLAUDE_PLUGIN_ID (timeout or error — re-run manually if needed)"
  fi
}

case "$mode" in
  all)
    install_claude_upstream_skills
    install_claude_local_plugin
    install_codex_upstream_skills
    install_codex_local_skills
    ;;
  claude)
    install_claude_upstream_skills
    install_claude_local_plugin
    ;;
  codex)
    install_codex_upstream_skills
    install_codex_local_skills
    ;;
esac
