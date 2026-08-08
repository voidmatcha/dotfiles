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

  # 로컬 스킬이 이깁니다.
  #
  # 이 저장소가 소유한 스킬과 이름이 겹치면 업스트림을 설치하지 않는다. 아래
  # 설치 경로는 심링크를 rm 으로 지우고 디렉터리로 갈아끼우므로, 가드가 없으면
  # 내가 쓴 스킬을 가리키던 링크가 어디를 가리켰는지 기록도 없이 사라진다.
  # 로컬 스킬은 저장소에 원본이 있고 업스트림은 언제든 다시 받을 수 있으니,
  # 충돌 시 잃으면 안 되는 쪽은 로컬이다.
  if [ -d "$LOCAL_SKILLS_DIR/$skill_name" ]; then
    warn "skipping upstream $tool_name skill '$skill_name': this repo owns a local skill with that name"
    return 0
  fi

  if $DRY_RUN; then
    info "[dry-run] install upstream $tool_name skill $skill_name from $url -> $dest"
    return 0
  fi

  # 심링크를 지우기 전에 어디를 가리켰는지 남긴다. 위 가드가 로컬 스킬은 이미
  # 막았지만, 사람이 손으로 만든 링크는 여전히 여기로 온다.
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

  # 로컬 수정을 조용히 버리지 않는다. 정상 설치 상태에서는 $dest 가 디렉터리라
  # 위쪽 백업 분기를 타지 않으므로, 여기서 파일 단위로 한 번 더 본다.
  # 내용이 같으면 아무것도 하지 않아 mtime 이 흔들리지 않는다.
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

# plugin.json 의 patch 자리를 하나 올린다. 사람이 버전을 기억할 필요를 없앤다.
# 저장소가 진실이므로 여기서 쓰고, 커밋은 사람이 한다.
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
        # 경고만 하면 매번 같은 줄이 나오고 결국 무시하게 된다. 실측에서 캐시가
        # 27일 묵어 있었고 스킬 두 개가 통째로 빠져 있었다.
        #
        # 캐시 무효화는 plugin.json 의 version 기준이므로, 내용이 바뀌었으면
        # 패치 자리를 올려서 update 가 실제로 새 사본을 뜨게 한다.
        warn "local Claude plugin skill content drift: source=$source_skill_count cached=$cached_skill_count"
        if bump_local_plugin_patch_version; then
          if with_timeout 300 claude plugin update "$CLAUDE_PLUGIN_ID" </dev/null; then
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
