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
OPENAI_SKILLS_REF="${OPENAI_SKILLS_REF:-a8924c2a35cfa290458852c4fad17c9133054c2e}"
FIGMA_IMPLEMENT_DESIGN_SKILL_URL="https://raw.githubusercontent.com/openai/skills/${OPENAI_SKILLS_REF}/skills/.curated/figma-implement-design/SKILL.md"
RETIRED_WORKFLOW_SKILLS=(autopilot ralplan ultraqa ultrawork)

usage() {
  cat <<'USAGE'
Usage: scripts/skills.sh [all|claude|codex] [--dry-run] [--retire-only]

Installs repo-local skills through the local plugin/skills path and upstream
standalone skills pinned for reproducibility:
  claude  registers this repo as local-skills@dotfiles-local and installs upstream Claude skills
  codex   symlinks plugins/local-skills/skills/* into ~/.codex/skills and installs upstream Codex skills
  all     does both (default)
  --retire-only  only retire obsolete workflow skills and the graphify package
USAGE
}

mode="all"
retire_only=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    all|claude|codex)
      mode="$1"
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --retire-only)
      retire_only=true
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

retire_workflow_skills() {
  local trash_dir="$HOME/.Trash/dotfiles-retired-workflow-skills"
  local name source destination surface index
  local -a skill_roots surfaces
  skill_roots=(
    "$CODEX_CONFIG_DIR/skills"
    "$HOME/.agents/skills"
    "$HOME/.claude/skills"
  )
  surfaces=(codex agents claude)

  for ((index = 0; index < ${#skill_roots[@]}; index++)); do
    surface="${surfaces[$index]}"
    for name in "${RETIRED_WORKFLOW_SKILLS[@]}"; do
      source="${skill_roots[$index]}/$name"
      if [ ! -e "$source" ] && [ ! -L "$source" ]; then
        continue
      fi
      destination="$trash_dir/$surface/$name"
      if [ -e "$destination" ] || [ -L "$destination" ]; then
        destination="$(next_backup_path "$destination")"
      fi
      if $DRY_RUN; then
        info "[dry-run] retire $surface workflow skill $name -> $destination"
        continue
      fi
      ensure_dir "$(dirname "$destination")"
      mv "$source" "$destination"
      info "Retired $surface workflow skill recoverably: $name -> $destination"
    done
  done
}

retire_legacy_graphify() {
  local graphify_command=""
  graphify_command="$(command -v graphify 2>/dev/null || true)"

  if ! command -v python3 >/dev/null 2>&1; then
    [ -z "$graphify_command" ] || \
      warn "graphify remains installed because python3 cannot verify its package owner"
    return 0
  fi
  if ! python3 -m pip show graphifyy >/dev/null 2>&1; then
    [ -z "$graphify_command" ] || \
      warn "graphify at $graphify_command is not owned by the graphifyy package; leaving it untouched"
    return 0
  fi
  if $DRY_RUN; then
    info "[dry-run] python3 -m pip uninstall -y graphifyy"
    return 0
  fi
  if python3 -m pip uninstall -y graphifyy >/dev/null; then
    hash -r 2>/dev/null || true
    info "Removed retired graphifyy package"
  else
    warn "Could not remove retired graphifyy package"
  fi
}

install_upstream_skill_from_url() {
  local tool_name="$1"
  local skills_dir="$2"
  local skill_name="$3"
  local url="$4"
  local dest="$skills_dir/$skill_name"
  local tmp_file backup_dst

  # Local skills win.
  #
  # If the name collides with a skill this repo owns, the upstream one is not
  # installed. The install path below rm's the symlink and swaps in a directory,
  # so without this guard a link pointing at a skill I wrote would disappear
  # with no record of where it pointed. A local skill has its original in the
  # repo and an upstream one can be re-downloaded at any time, so on a collision
  # the side that must not be lost is the local one.
  if [ -d "$LOCAL_SKILLS_DIR/$skill_name" ]; then
    warn "skipping upstream $tool_name skill '$skill_name': this repo owns a local skill with that name"
    return 0
  fi

  if $DRY_RUN; then
    info "[dry-run] install upstream $tool_name skill $skill_name from $url -> $dest"
    return 0
  fi

  # Record where the symlink pointed before deleting it. The guard above already
  # blocked local skills, but a link made by hand still reaches this point.
  if [ -L "$dest" ]; then
    warn "replacing symlink $dest -> $(readlink "$dest" 2>/dev/null || printf '?')"
  fi

  ensure_dir "$skills_dir"
  tmp_file="$(mktemp)"
  if ! curl -fsSL "$url" -o "$tmp_file"; then
    rm -f "$tmp_file"
    warn "Failed upstream $tool_name skill download: $skill_name ($url)"
    return 1
  fi

  if ! grep -q '^name: '"$skill_name"'$' "$tmp_file"; then
    rm -f "$tmp_file"
    warn "Downloaded upstream skill has unexpected name; skipping: $skill_name"
    return 1
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

  # Never drop local edits silently. In a normal install $dest is a directory,
  # so the backup branch above is not taken; look once more at file level here.
  # If the content is identical nothing happens, so the mtime does not move.
  if [ -f "$dest/SKILL.md" ]; then
    if cmp -s "$dest/SKILL.md" "$tmp_file"; then
      rm -f "$tmp_file"
      info "Upstream $tool_name skill already current: $skill_name"
      return 0
    fi
    backup_dst="$(next_backup_path "$dest/SKILL.md")"
    warn "Local edits found in $skill_name; backing up -> $backup_dst"
    cp "$dest/SKILL.md" "$backup_dst"
  fi

  mv "$tmp_file" "$dest/SKILL.md"
  info "Installed upstream $tool_name skill: $skill_name -> $dest"
}

install_claude_upstream_skills() {
  install_upstream_skill_from_url "Claude" "$HOME/.claude/skills" "grill-me" "$GRILL_ME_SKILL_URL"
}

install_codex_upstream_skills() {
  install_upstream_skill_from_url "Codex" "$CODEX_CONFIG_DIR/skills" "grill-me" "$GRILL_ME_SKILL_URL"
  install_upstream_skill_from_url "Codex" "$CODEX_CONFIG_DIR/skills" "figma-implement-design" "$FIGMA_IMPLEMENT_DESIGN_SKILL_URL"
}

install_codex_local_skills() {
  local skills_dir="$CODEX_CONFIG_DIR/skills"
  local skill_dir skill_name dest backup_dst existing_link target

  if [ ! -d "$LOCAL_SKILLS_DIR" ]; then
    warn "local skills directory not found: $LOCAL_SKILLS_DIR"
    return 1
  fi

  ensure_dir "$skills_dir"

  while IFS= read -r existing_link; do
    target="$(readlink "$existing_link" || true)"
    case "$target" in
      "$LOCAL_SKILLS_DIR"/*)
        if [ ! -e "$target" ]; then
          if $DRY_RUN; then
            info "[dry-run] remove stale local Codex skill symlink $existing_link -> $target"
          else
            rm "$existing_link"
            info "Removed stale local Codex skill symlink: $(basename "$existing_link")"
          fi
        fi
        ;;
    esac
  done < <(find "$skills_dir" -mindepth 1 -maxdepth 1 -type l | sort)

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

# Bump the patch position in plugin.json by one, so nobody has to remember the
# version. The repo is the truth, so it is written here and the human commits.
bump_local_plugin_patch_version() {
  if $DRY_RUN; then
    info "[dry-run] bump local plugin patch version"
    return 0
  fi
  python3 "$DOTFILES_DIR/scripts/bump_local_plugin_version.py" "$LOCAL_PLUGIN_DIR"
}

local_plugin_skill_snapshot() {
  local skills_dir="$1"
  python3 - "$skills_dir" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
if not root.is_dir():
    raise SystemExit(0)

def distributable(path: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts):
        return False
    return path.name != ".DS_Store" and path.suffix not in {".pyc", ".pyo"}


for path in sorted(
    (candidate for candidate in root.rglob("*") if distributable(candidate)),
    key=lambda item: item.relative_to(root).as_posix(),
):
    relative = path.relative_to(root).as_posix()
    if path.is_symlink():
        print(f"L\t{relative}\t{os.readlink(path)}")
    elif path.is_file():
        mode = stat.S_IMODE(path.stat().st_mode)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"F\t{relative}\t{mode:04o}\t{digest}")
PY
}

local_plugin_skill_count() {
  local skills_dir="$1"
  if [ ! -d "$skills_dir" ]; then
    printf '0'
    return 0
  fi
  find "$skills_dir" -mindepth 2 -maxdepth 2 -type f -name SKILL.md | wc -l | tr -d ' '
}

install_claude_local_plugin() {
  local marketplace_manifest="$DOTFILES_DIR/.claude-plugin/marketplace.json"
  local claude_manifest="$LOCAL_PLUGIN_DIR/.claude-plugin/plugin.json"
  local codex_manifest="$LOCAL_PLUGIN_DIR/.codex-plugin/plugin.json"
  local marketplace_version claude_version codex_version
  local failed=0

  if [ ! -f "$marketplace_manifest" ] || [ ! -f "$claude_manifest" ] || [ ! -f "$codex_manifest" ]; then
    warn "local Claude plugin manifest missing under $DOTFILES_DIR/.claude-plugin or $LOCAL_PLUGIN_DIR/.claude-plugin"
    return 1
  fi

  # A fresh-machine dry run happens before jq/Claude are installed. Keep the
  # preview useful without claiming machine-state knowledge or reading cached
  # inventories that cannot yet be validated.
  if $DRY_RUN && ! command -v jq &>/dev/null; then
    info "[dry-run] add or update local Claude marketplace: $DOTFILES_DIR"
    info "[dry-run] install or update local Claude plugin: $CLAUDE_PLUGIN_ID"
    return 0
  fi

  if ! command -v jq &>/dev/null; then
    warn "jq not found; cannot validate local plugin manifest/inventory state"
    return 1
  fi

  marketplace_version=$(jq -er --arg n "local-skills" \
    '.plugins[] | select(.name == $n) | .version' "$marketplace_manifest" 2>/dev/null) || {
      warn "local Claude marketplace has no version for local-skills"
      return 1
    }
  claude_version=$(jq -er '.version' "$claude_manifest" 2>/dev/null) || {
    warn "local Claude plugin manifest has no version"
    return 1
  }
  codex_version=$(jq -er '.version' "$codex_manifest" 2>/dev/null) || {
    warn "local Codex plugin manifest has no version"
    return 1
  }
  if [ "$marketplace_version" != "$claude_version" ] || [ "$claude_version" != "$codex_version" ]; then
    warn "local plugin manifest version drift: marketplace=$marketplace_version claude=$claude_version codex=$codex_version"
    return 1
  fi

  if $DRY_RUN; then
    # shellcheck disable=SC2016 # jq variables are passed via --arg.
    if json_entry_exists "$CLAUDE_KNOWN_MARKETPLACES_JSON" 'has($n)' --arg n "$CLAUDE_MARKETPLACE_NAME"; then
      info "[dry-run] claude plugin marketplace update $CLAUDE_MARKETPLACE_NAME"
    else
      info "[dry-run] claude plugin marketplace add $DOTFILES_DIR"
    fi
    # shellcheck disable=SC2016 # jq variables are passed via --arg.
    if json_entry_exists "$CLAUDE_INSTALLED_PLUGINS_JSON" '.plugins | has($p)' --arg p "$CLAUDE_PLUGIN_ID"; then
      info "[dry-run] claude plugin update $CLAUDE_PLUGIN_ID"
    else
      info "[dry-run] claude plugin install $CLAUDE_PLUGIN_ID"
    fi
    return 0
  fi

  if ! command -v claude &>/dev/null; then
    warn "claude not found; cannot install the local Claude plugin"
    return 1
  fi

  ensure_dir "$HOME/.claude/plugins"

  # shellcheck disable=SC2016 # jq variables are passed via --arg.
  if json_entry_exists "$CLAUDE_KNOWN_MARKETPLACES_JSON" 'has($n)' --arg n "$CLAUDE_MARKETPLACE_NAME"; then
    if with_timeout 180 claude plugin marketplace update "$CLAUDE_MARKETPLACE_NAME" </dev/null; then
      info "Updated local Claude marketplace: $CLAUDE_MARKETPLACE_NAME"
    else
      warn "Failed to update local Claude marketplace: $CLAUDE_MARKETPLACE_NAME"
      failed=1
    fi
  elif with_timeout 180 claude plugin marketplace add "$DOTFILES_DIR" </dev/null; then
    info "Added local Claude marketplace: $CLAUDE_MARKETPLACE_NAME"
  else
    warn "Failed local Claude marketplace: $CLAUDE_MARKETPLACE_NAME (timeout or error — re-run manually if needed)"
    failed=1
  fi

  # shellcheck disable=SC2016 # jq variables are passed via --arg.
  if json_entry_exists "$CLAUDE_INSTALLED_PLUGINS_JSON" '.plugins | has($p)' --arg p "$CLAUDE_PLUGIN_ID"; then
    if with_timeout 180 claude plugin update "$CLAUDE_PLUGIN_ID" </dev/null; then
      info "Updated local Claude plugin: $CLAUDE_PLUGIN_ID"
    else
      warn "Failed to update local Claude plugin: $CLAUDE_PLUGIN_ID"
      failed=1
    fi
  elif with_timeout 180 claude plugin install "$CLAUDE_PLUGIN_ID" </dev/null; then
    info "Installed local Claude plugin: $CLAUDE_PLUGIN_ID"
  else
    warn "Failed local Claude plugin: $CLAUDE_PLUGIN_ID (timeout or error — re-run manually if needed)"
    failed=1
  fi

  # Claude copies installed plugins into a versioned cache and records that
  # path/version in installed_plugins.json. A successful CLI exit is not enough:
  # stale inventory leaves new source skills invisible until a later session.
  local installed_entry install_path cached_version
  local source_skill_snapshot cached_skill_snapshot source_skill_count cached_skill_count
  installed_entry=$(jq -cer --arg p "$CLAUDE_PLUGIN_ID" --arg v "$claude_version" \
    '([.plugins[$p][]? | select(.version == $v)] | last) // empty' \
    "$CLAUDE_INSTALLED_PLUGINS_JSON" 2>/dev/null) || installed_entry=""
  if [ -z "$installed_entry" ]; then
    warn "local Claude plugin inventory/cache drift: expected $CLAUDE_PLUGIN_ID@$claude_version in $CLAUDE_INSTALLED_PLUGINS_JSON"
    failed=1
  else
    install_path=$(printf '%s' "$installed_entry" | jq -er '.installPath' 2>/dev/null) || install_path=""
    cached_version=""
    if [ -n "$install_path" ] && [ -f "$install_path/.claude-plugin/plugin.json" ]; then
      cached_version=$(jq -er '.version' "$install_path/.claude-plugin/plugin.json" 2>/dev/null) || cached_version=""
    fi
    case "$install_path" in
      "$HOME/.claude/plugins/cache/"*) ;;
      *) install_path="" ;;
    esac
    if [ -z "$install_path" ] || [ "$cached_version" != "$claude_version" ]; then
      warn "local Claude plugin inventory/cache drift: expected cached manifest version $claude_version"
      failed=1
    else
      source_skill_snapshot=$(local_plugin_skill_snapshot "$LOCAL_SKILLS_DIR")
      cached_skill_snapshot=$(local_plugin_skill_snapshot "$install_path/skills")
      source_skill_count=$(local_plugin_skill_count "$LOCAL_SKILLS_DIR")
      cached_skill_count=$(local_plugin_skill_count "$install_path/skills")
      if [ -z "$source_skill_snapshot" ] || [ "$source_skill_snapshot" != "$cached_skill_snapshot" ]; then
        # Warning alone prints the same line every time and ends up ignored.
        # Measured: the cache was 27 days old and two skills were missing whole.
        #
        # Cache invalidation keys off the version in plugin.json, so when the
        # content changed, bump the patch position to make update actually pull
        # a fresh copy.
        warn "local Claude plugin skill content drift: source=$source_skill_count cached=$cached_skill_count"
        if bump_local_plugin_patch_version; then
          # The bump changes the marketplace manifest after the earlier
          # marketplace refresh. Refresh it again before updating the plugin;
          # otherwise Claude can create the new version directory from stale
          # marketplace content and repeat this bump forever.
          if ! with_timeout 180 claude plugin marketplace update "$CLAUDE_MARKETPLACE_NAME" </dev/null; then
            warn "version bumped but marketplace refresh failed; not updating from stale content"
            failed=1
          elif with_timeout 300 claude plugin update "$CLAUDE_PLUGIN_ID" </dev/null; then
            info "bumped local plugin version and refreshed the cache"
          else
            warn "version bumped but 'claude plugin update' failed; run it manually"
            failed=1
          fi
        else
          failed=1
        fi
      else
        info "Verified local Claude plugin content/cache: $CLAUDE_PLUGIN_ID@$claude_version ($source_skill_count skills)"
      fi
    fi
  fi

  return "$failed"
}

retire_workflow_skills
retire_legacy_graphify
$retire_only && exit 0

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
