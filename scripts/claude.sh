#!/bin/bash
set -euo pipefail
TAG="claude"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

info "Setting up Claude Code..."

# ── Claude Code binary (native install) ──
# Install the native build into ~/.local instead of via Homebrew. The cask
# lags upstream and is shadowed by ~/.local/bin on PATH anyway, while the
# native build self-manages versions through `claude update`. Provision by
# downloading the official installer and running it from disk — curl-pipe-bash
# is denied by our pretool-guard, and download-then-run lets the script be
# inspected first. An explicit --upgrade checks an installed binary; setup-only
# reruns preserve it. A missing binary uses the stable installer.
install_claude_code() {
  if command -v claude &>/dev/null; then
    info "claude present ($(claude --version 2>/dev/null | awk '{print $1}'))"
    if $UPGRADE; then
      if $DRY_RUN; then
        info "[dry-run] claude update"
      else
        with_timeout 120 claude update </dev/null \
          || warn "claude update failed/timed out (continuing with the installed build)"
      fi
    fi
    return 0
  fi

  if $DRY_RUN; then
    info "[dry-run] download https://claude.ai/install.sh and run it (native build, stable channel)"
    return 0
  fi

  local installer
  installer=$(mktemp)
  if curl -fsSL https://claude.ai/install.sh -o "$installer" && bash "$installer"; then
    info "Installed Claude Code native build to ~/.local"
  else
    warn "Claude Code native install failed — install manually: https://docs.claude.com/en/docs/claude-code/setup"
  fi
  rm -f "$installer"

  # The native installer drops the binary in ~/.local/bin; make it visible to
  # the rest of this script (claude plugin / mcp …) even if PATH wasn't
  # refreshed in this shell.
  command -v claude &>/dev/null || export PATH="$HOME/.local/bin:$PATH"
  if ! command -v claude &>/dev/null; then
    warn "Claude Code is still unavailable after the native install attempt"
    return 1
  fi
}
install_claude_code

# npm 11.x breaks npx for packages not in package.json.
ensure_npm_global_latest "skills" "skills" \
  || warn "skills CLI install/update failed — continuing with the installed version"

SKILL_REPOS=(
  "voidmatcha/e2e-skills"
  # voidmatcha/ui-clone-skills: handled separately below via the upstream
  # install.sh — the `skills add` path skips required system tooling
  # (uv, ffmpeg, imagemagick, dssim, agent-browser) and the ui_clone/
  # Python package, both of which the skill's preflight checks expect.
)

RETIRED_GLOBAL_SKILLS=(
  "humanizer"
  "humanize"
  "humanize-korean"
  "humanize-redo"
  "karpathy-guidelines"
  "doc-coauthoring"
  "frontend-design"
  "internal-comms"
  "webapp-testing"
  "mcp-builder"
  "skill-creator"
  "graphify"
)

for repo in "${SKILL_REPOS[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] skills add $repo --yes --global --agent claude-code"
  else
    if skills add "$repo" --yes --global --agent claude-code 2> >(grep -v "invalid option" >&2); then
      info "Installed: $repo"
    else
      info "⚠️  Failed: $repo"
    fi
  fi
done

if $DRY_RUN; then
  info "[dry-run] skills remove ${RETIRED_GLOBAL_SKILLS[*]} --global --yes"
elif command -v skills &>/dev/null; then
  if skills remove "${RETIRED_GLOBAL_SKILLS[@]}" --global --yes; then
    info "Removed retired global skills"
  else
    warn "Retired global skill cleanup failed; existing skills were left visible"
  fi
fi

# Repo-local skills/plugin bundle. This keeps locally-authored skills in this
# repository and installs them through the same setup path instead of scattering
# copies under ~/.claude or ~/.codex.
if [ -x "$DOTFILES_DIR/scripts/skills.sh" ]; then
  bash "$DOTFILES_DIR/scripts/skills.sh" claude
fi

# ── ui-clone-skills — install via upstream installer ──
# The `skills add voidmatcha/ui-clone-skills` path skips required system
# tooling (uv, ffmpeg, imagemagick, dssim, agent-browser) and the ui_clone/
# Python package. The repo's own install.sh provisions all of that and
# registers the local checkout as a Claude Code marketplace. Clone first
# (curl-pipe-bash is denied by our pretool-guard for good reason), then run
# the on-disk installer.
UI_CLONE_DIR="${UI_CLONE_INSTALL_DIR:-$HOME/.local/share/ui-clone-skills}"

remove_tracked_claude_local_marketplace() {
  local settings_file="$DOTFILES_DIR/configs/claude-settings.json"
  [ -f "$settings_file" ] || return 0

  if ! command -v python3 &>/dev/null; then
    warn "python3 not found — cannot clean machine-local Claude marketplace entry"
    return 0
  fi

  local changed
  changed=$(python3 - "$settings_file" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
cfg = json.loads(path.read_text())
marketplaces = cfg.get("extraKnownMarketplaces")
if not isinstance(marketplaces, dict):
    raise SystemExit(0)

# Any directory-source marketplace with a home-anchored path is machine-local
# pollution: `claude plugin marketplace add` persists such registrations into
# settings.json, and when that lands in the tracked file it breaks installs on
# other machines/usernames. skills.sh / the ui-clone installer re-register
# them locally on every install, so stripping here loses nothing.
home_prefixes = ("/" + "Users" + "/", "/" + "home" + "/")
stale = [
    name for name, entry in marketplaces.items()
    if isinstance(entry, dict)
    and isinstance(entry.get("source"), dict)
    and entry["source"].get("source") == "directory"
    and entry["source"].get("path", "").startswith(home_prefixes)
]
if stale:
    for name in stale:
        del marketplaces[name]
    if not marketplaces:
        del cfg["extraKnownMarketplaces"]
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    print("changed")
PY
)

  if [ "$changed" = "changed" ]; then
    info "Removed machine-local Claude marketplace path from shared settings"
  fi
}

cleanup_ui_clone_staging_venv() {
  local staging_parent="$HOME/.local/share"
  local staging_source="$staging_parent/ui-clone-skills-claude-src"
  local staging_venv="$staging_source/.venv"
  local parent_real source_real

  if [ ! -e "$staging_venv" ] && [ ! -L "$staging_venv" ]; then
    return 0
  fi
  if [ -L "$staging_source" ]; then
    warn "ui-clone-skills: refusing symlinked staging source cleanup"
    return 1
  fi
  if [ -L "$staging_venv" ]; then
    warn "ui-clone-skills: refusing symlinked staging venv cleanup"
    return 1
  fi
  if [ ! -d "$staging_venv" ]; then
    warn "ui-clone-skills: staging .venv is not a directory; leaving it untouched"
    return 1
  fi

  parent_real=$(cd "$staging_parent" 2>/dev/null && pwd -P) || {
    warn "ui-clone-skills: could not resolve staging parent; leaving .venv untouched"
    return 1
  }
  source_real=$(cd "$staging_source" 2>/dev/null && pwd -P) || {
    warn "ui-clone-skills: could not resolve staging source; leaving .venv untouched"
    return 1
  }
  if [ "$source_real" != "$parent_real/ui-clone-skills-claude-src" ]; then
    warn "ui-clone-skills: staging source escaped its expected boundary"
    return 1
  fi

  rm -rf -- "$staging_venv"
  info "ui-clone-skills: removed disabled Claude staging environment"
}

restore_ui_clone_plugin_policy() {
  local plugin="ui-clone-skills@voidmatcha"

  # The upstream installer enables its plugin after every refresh. Keep it
  # installed for project-specific use, but restore this repo's user-scope
  # default so unrelated Claude sessions do not load the full UI harness.
  if [ "${UI_CLONE_PLUGIN_POLICY:-true}" = "false" ]; then
    if claude plugin disable "$plugin" --scope user >/dev/null 2>&1; then
      info "ui-clone-skills: restored disabled-by-default policy"
    else
      warn "ui-clone-skills: could not restore disabled-by-default policy"
    fi

    # Cleanup is intentionally fixed to the default disposable staging source.
    # UI_CLONE_CLAUDE_SRC_DIR may point at a real checkout and is never a
    # deletion authority.
    cleanup_ui_clone_staging_venv || true
  fi
}

run_ui_clone_installer() {
  # The upstream delivery probe intentionally warms a 200+ MB uv environment
  # inside Claude's plugin cache. Skip that warm-up when this repo will disable
  # the plugin immediately; Codex uses the separate live checkout.
  if [ "${UI_CLONE_PLUGIN_POLICY:-true}" = "false" ]; then
    UI_CLONE_SKIP_HOOK_PROBE=1 \
      "$UI_CLONE_DIR/install.sh" "$@"
  else
    "$UI_CLONE_DIR/install.sh" "$@"
  fi
}

UI_CLONE_PLUGIN_POLICY="$(jq -r \
  '.enabledPlugins["ui-clone-skills@voidmatcha"] // false' \
  "$DOTFILES_DIR/configs/claude-settings.json" 2>/dev/null || printf 'false')"

if $DRY_RUN; then
  info "[dry-run] would clone voidmatcha/ui-clone-skills to $UI_CLONE_DIR and run install.sh"
else
  if [ -d "$UI_CLONE_DIR/.claude-plugin" ]; then
    info "ui-clone-skills: updating $UI_CLONE_DIR"
    git -C "$UI_CLONE_DIR" pull --ff-only --quiet 2>/dev/null \
      || warn "  ui-clone-skills: local changes prevent fast-forward (leaving as-is)"
  else
    info "ui-clone-skills: cloning to $UI_CLONE_DIR"
    ensure_dir "$(dirname "$UI_CLONE_DIR")"
    if ! git clone --quiet https://github.com/voidmatcha/ui-clone-skills.git "$UI_CLONE_DIR"; then
      warn "ui-clone-skills: clone failed, skipping installer"
      UI_CLONE_DIR=""
    fi
  fi

  if [ -n "$UI_CLONE_DIR" ] && [ -x "$UI_CLONE_DIR/install.sh" ]; then
    ui_clone_flags=()
    $NON_INTERACTIVE && ui_clone_flags+=(--yes)
    # ${arr[@]+...} avoids "unbound variable" under `set -u` when the array
    # is empty (bash 3.2 on macOS still trips on a bare "${arr[@]}" here).
    if run_ui_clone_installer ${ui_clone_flags[@]+"${ui_clone_flags[@]}"}; then
      info "ui-clone-skills: install.sh OK — run '/plugin install ui-clone-skills@voidmatcha' inside Claude Code to activate"
    else
      warn "ui-clone-skills: install.sh exited non-zero"
    fi
    restore_ui_clone_plugin_policy
  fi
  remove_tracked_claude_local_marketplace
fi

PLUGIN_MARKETPLACES=(
  "jarrodwatts/claude-hud"
  "thedotmack/claude-mem"
)

PLUGINS=(
  "claude-hud@claude-hud"
  "security-guidance@claude-plugins-official"
  "claude-mem@thedotmack"
)

RETIRED_PLUGINS=(
  "codex@openai-codex"
  "ralph-loop@claude-plugins-official"
  "autoresearch@autoresearch"
  "skills-janitor@skills-janitor"
  "superpowers@claude-plugins-official"
  "frontend-design@claude-plugins-official"
  "rust-analyzer-lsp@claude-plugins-official"
  "fakechat@claude-plugins-official"
  "vercel@claude-plugins-official"
  "session-report@claude-plugins-official"
  "claude-md-management@claude-plugins-official"
  "hookify@claude-plugins-official"
  "review-loop@hamel-review"
  "comprehensive-review@claude-code-workflows"
  "javascript-typescript@claude-code-workflows"
  "python-development@claude-code-workflows"
  "frontend-mobile-development@claude-code-workflows"
  "security-scanning@claude-code-workflows"
  "documentation-generation@claude-code-workflows"
  "unit-testing@claude-code-workflows"
  "git-pr-workflows@claude-code-workflows"
  "tdd-workflows@claude-code-workflows"
  "error-debugging@claude-code-workflows"
  "ui-design@claude-code-workflows"
  "accessibility-compliance@claude-code-workflows"
  "content-marketing@claude-code-workflows"
  "seo-content-creation@claude-code-workflows"
  "seo-technical-optimization@claude-code-workflows"
  "seo-analysis-monitoring@claude-code-workflows"
)

RETIRED_MARKETPLACES=(
  "openai-codex"
  "skills-janitor"
  "claude-code-workflows"
  "autoresearch"
  "hamel-review"
)

info "Installing Claude Code Plugins..."

# `claude plugin` is interactive when the marketplace/plugin is already
# registered (confirmation prompt) — and stdin redirect doesn't bypass it
# because Claude Code reads from /dev/tty. So we check state JSON first and
# route to install or update accordingly. 180s timeout is the last-resort
# safety net for first-time installs that legitimately stall.
KNOWN_MARKETPLACES_JSON="$HOME/.claude/plugins/known_marketplaces.json"
INSTALLED_PLUGINS_JSON="$HOME/.claude/plugins/installed_plugins.json"
# shellcheck disable=SC2016 # jq variables are passed via --arg.
MARKETPLACE_REPO_FILTER='to_entries[] | select(.value.source.repo == $r)'
# A plugin key can hold entries from several project/user scopes. Setup owns
# only the user entry; project installations belong to those projects.
# shellcheck disable=SC2016 # jq variables are passed via --arg.
INSTALLED_PLUGIN_FILTER='any(.plugins[$p][]?; .scope == "user")'
# shellcheck disable=SC2016 # jq variables are passed via --arg.
MARKETPLACE_NAME_FILTER='has($m)'

for marketplace in "${PLUGIN_MARKETPLACES[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] claude plugin marketplace add $marketplace"
  elif json_entry_exists "$KNOWN_MARKETPLACES_JSON" \
      "$MARKETPLACE_REPO_FILTER" --arg r "$marketplace"; then
    info "Marketplace already registered: $marketplace"
  else
    if with_timeout 180 claude plugin marketplace add "$marketplace" </dev/null; then
      info "Added marketplace: $marketplace"
    else
      info "⚠️  Failed marketplace: $marketplace (timeout or error — re-run manually if needed)"
    fi
  fi
done

for plugin in "${RETIRED_PLUGINS[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] claude plugin uninstall $plugin"
  elif json_entry_exists "$INSTALLED_PLUGINS_JSON" "$INSTALLED_PLUGIN_FILTER" --arg p "$plugin"; then
    if with_timeout 60 claude plugin uninstall --scope user --yes "$plugin" </dev/null; then
      info "Uninstalled retired plugin: $plugin"
    else
      warn "Could not uninstall retired plugin: $plugin"
    fi
  fi
done

for marketplace in "${RETIRED_MARKETPLACES[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] claude plugin marketplace remove $marketplace"
  elif json_entry_exists "$KNOWN_MARKETPLACES_JSON" \
      "$MARKETPLACE_NAME_FILTER" --arg m "$marketplace"; then
    if with_timeout 60 claude plugin marketplace remove "$marketplace" </dev/null; then
      info "Removed retired marketplace: $marketplace"
    else
      warn "Could not remove retired marketplace: $marketplace"
    fi
  fi
done

# Refresh every registered marketplace before the install/update pass. Without
# this, `claude plugin update` compares against a stale cached manifest and
# reports "already up to date" even when upstream has newer releases. Bare
# `marketplace update` refreshes all of them.
if $DRY_RUN; then
  info "[dry-run] claude plugin marketplace update"
else
  with_timeout 180 claude plugin marketplace update </dev/null >/dev/null \
    || warn "marketplace refresh failed/timed out — plugin updates may be stale"
fi

# Install what is missing, update what is present. Skipping installed plugins
# entirely lets them drift: claude-mem sat on 13.2.0 while upstream shipped
# 13.13.1, which cost us two months of Codex hook fixes. `plugin update` is a
# no-op when already current, so running it unconditionally is cheap.
for plugin in "${PLUGINS[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] claude plugin install-or-update $plugin"
  elif json_entry_exists "$INSTALLED_PLUGINS_JSON" "$INSTALLED_PLUGIN_FILTER" --arg p "$plugin"; then
    if with_timeout 300 claude plugin update "$plugin" </dev/null; then
      info "Checked for updates: $plugin"
    else
      warn "Update check failed for $plugin (timeout or error — re-run manually if needed)"
    fi
  else
    if with_timeout 180 claude plugin install "$plugin" </dev/null; then
      info "Installed plugin: $plugin"
    else
      info "⚠️  Failed plugin: $plugin (timeout or error — re-run manually if needed)"
    fi
  fi
done

if $DRY_RUN; then
  info "[dry-run] claude plugin list"
else
  with_timeout 30 claude plugin list </dev/null || warn "claude plugin list failed/timed out — verify plugin activation manually"
fi

# ── MCP servers (user scope) ──
# Claude Code stores user-scope MCP entries in ~/.claude.json (managed via
# `claude mcp add-json`). Symlinking configs/mcp.json into ~/.claude/.mcp.json
# does NOT work — verified: `claude mcp add --scope user` writes to
# ~/.claude.json directly.
RETIRED_USER_MCPS=(
  "chrome-devtools"
)

prune_retired_user_mcps() {
  local name cleanup_failed=0
  for name in "${RETIRED_USER_MCPS[@]}"; do
    if $DRY_RUN; then
      info "[dry-run] claude mcp remove --scope user $name (if present)"
      continue
    fi

    # Leave independently managed MCPs untouched. This allowlist contains only
    # registrations that this repository used to own and has since retired.
    # shellcheck disable=SC2016 # jq variable is passed via --arg.
    if ! json_entry_exists "$HOME/.claude.json" '.mcpServers[$n] != null' \
        --arg n "$name"; then
      continue
    fi
    if ! command -v claude &>/dev/null; then
      warn "claude not available — cannot remove retired MCP: $name"
      cleanup_failed=1
      continue
    fi

    # shellcheck disable=SC2016 # jq variable is passed via --arg.
    if with_timeout 30 claude mcp remove --scope user "$name" >/dev/null 2>&1 \
        && ! json_entry_exists "$HOME/.claude.json" '.mcpServers[$n] != null' \
          --arg n "$name"; then
      info "Removed retired user-scope MCP: $name"
    else
      warn "Failed to remove retired user-scope MCP: $name"
      cleanup_failed=1
    fi
  done
  return "$cleanup_failed"
}

restore_mcp_entry() {
  local name="$1" entry="$2"
  with_timeout 30 claude mcp remove --scope user "$name" >/dev/null 2>&1 || true
  with_timeout 30 claude mcp add-json --scope user "$name" "$entry" >/dev/null 2>&1 || return 1
  # shellcheck disable=SC2016 # jq variables are passed via --arg/--argjson.
  json_entry_exists "$HOME/.claude.json" '.mcpServers[$n] == $e' \
    --arg n "$name" --argjson e "$entry"
}

register_mcp_from_file() {
  local mcp_file="$1"
  if [ ! -f "$mcp_file" ]; then
    return 0
  fi
  if $DRY_RUN; then
    local preview_names preview_name
    if command -v python3 &>/dev/null; then
      preview_names=$(python3 - "$mcp_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
servers = data.get("mcpServers")
if not isinstance(servers, dict) or not all(isinstance(name, str) and name for name in servers):
    raise SystemExit("mcpServers must be an object with non-empty string keys")
if not all(isinstance(entry, dict) for entry in servers.values()):
    raise SystemExit("every MCP entry must be an object")
for name in sorted(servers):
    print(name)
PY
      ) || {
        warn "invalid MCP configuration: $mcp_file"
        return 1
      }
      while IFS= read -r preview_name; do
        [ -z "$preview_name" ] || \
          info "[dry-run] claude mcp add-json --scope user $preview_name '<redacted>'"
      done <<< "$preview_names"
    else
      info "[dry-run] register user-scope MCP servers from $mcp_file (entry JSON hidden)"
    fi
    return 0
  fi
  if ! command -v jq &>/dev/null || ! command -v claude &>/dev/null; then
    warn "jq or claude not available — cannot register MCPs from $mcp_file"
    return 1
  fi

  local names registration_failed=0
  names=$(jq -r '.mcpServers | keys[]' "$mcp_file" 2>/dev/null)
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    local raw_entry entry old_entry install_status rollback_status
    # Use --arg to safely pass the key (avoids jq filter string-interpolation
    # injection). Validate the source object before replacing a working entry.
    raw_entry=$(jq -c --arg n "$name" '.mcpServers[$n]' "$mcp_file")
    if ! printf '%s' "$raw_entry" | jq -e 'type == "object"' >/dev/null 2>&1; then
      warn "Invalid MCP $name: entry must be a JSON object (keeping existing config)"
      registration_failed=1
      continue
    fi
    # Claude Code expands ${VAR} placeholders when it starts. Store those
    # references verbatim so credentials stay in Keychain/process scope instead
    # of being rendered into ~/.claude.json during installation.
    entry="$raw_entry"
    if ! printf '%s' "$entry" | jq -e . >/dev/null 2>&1; then
      warn "Skipping MCP $name: entry is invalid JSON (keeping existing config)"
      registration_failed=1
      continue
    fi
    # Already registered with the exact same config → leave it alone. This is
    # the common path on re-runs, and it avoids the remove→add window below,
    # which drops a working entry whenever the add fails (policy block,
    # CLI hang). add-json stores the entry verbatim, so equality is reliable.
    # shellcheck disable=SC2016 # jq variables are passed via --arg/--argjson.
    if json_entry_exists "$HOME/.claude.json" '.mcpServers[$n] == $e' \
        --arg n "$name" --argjson e "$entry"; then
      info "MCP already registered: $name"
      continue
    fi

    # Back up the exact old entry before remove (add-json refuses to overwrite).
    # If the replacement fails, immediately restore this JSON instead of
    # leaving the user with no working registration.
    old_entry=$(jq -cer --arg n "$name" '.mcpServers[$n] // empty' \
      "$HOME/.claude.json" 2>/dev/null) || old_entry=""
    if [ -n "$old_entry" ]; then
      info "Backing up existing MCP config before replacement: $name"
      if ! with_timeout 30 claude mcp remove --scope user "$name" >/dev/null 2>&1; then
        registration_failed=1
        if json_entry_exists "$HOME/.claude.json" '.mcpServers[$n] == $e' \
            --arg n "$name" --argjson e "$old_entry"; then
          warn "Failed to remove existing MCP: $name (verified existing config is intact)"
        elif restore_mcp_entry "$name" "$old_entry"; then
          warn "MCP remove failed after mutating config; restored and verified previous config: $name"
        else
          warn "CRITICAL: MCP remove failed and previous config could not be restored: $name"
        fi
        continue
      fi
    fi

    # 30s timeout: `claude` CLI subcommands have been observed to hang on
    # certain machines/versions; don't let MCP setup stall install.sh. The CLI
    # exit code is not sufficient: verify the user config postcondition too.
    local replacement_ok=0
    if with_timeout 30 claude mcp add-json --scope user "$name" "$entry" >/dev/null 2>&1; then
      # shellcheck disable=SC2016 # jq variables are passed via --arg/--argjson.
      if json_entry_exists "$HOME/.claude.json" '.mcpServers[$n] == $e' \
          --arg n "$name" --argjson e "$entry"; then
        replacement_ok=1
        info "Registered and verified MCP: $name"
      else
        warn "Failed to verify registered MCP postcondition: $name"
      fi
    else
      install_status=$?
      # add-json can receive credential-bearing JSON. Never echo its diagnostics
      # because a failing CLI may print the full rejected argument back.
      warn "Failed to register MCP: $name (exit $install_status; CLI output suppressed to protect credentials)"
    fi

    if [ "$replacement_ok" -ne 1 ]; then
      registration_failed=1
      if [ -n "$old_entry" ]; then
        # A failed/lying add may still have left a partial entry. Restore the
        # exact backup through the same verified transaction helper.
        rollback_status=0
        if restore_mcp_entry "$name" "$old_entry"; then
          warn "MCP replacement failed; restored and verified previous config: $name"
        else
          rollback_status=$?
          warn "CRITICAL: MCP rollback failed verification for $name (exit $rollback_status; CLI output suppressed to protect credentials)"
        fi
      else
        # No prior entry existed, so remove any unverified partial registration.
        with_timeout 30 claude mcp remove --scope user "$name" >/dev/null 2>&1 || true
      fi
    fi
  done <<< "$names"

  return "$registration_failed"
}

if ! prune_retired_user_mcps; then
  warn "Retired user-scope MCP cleanup was incomplete"
fi

info "Registering user-scope MCP servers from configs/mcp.json..."
register_mcp_from_file "$DOTFILES_DIR/configs/mcp.json"

# session-wrap overlaps the llmwiki/handover lifecycle. Retire the old manually
# installed directory recoverably instead of leaving an untracked active plugin.
SESSION_WRAP_DIR="$HOME/.claude/plugins/session-wrap"
if [ -d "$SESSION_WRAP_DIR" ]; then
  SESSION_WRAP_TRASH="$(next_backup_path "$HOME/.Trash/session-wrap")"
  if $DRY_RUN; then
    info "[dry-run] retire session-wrap -> $SESSION_WRAP_TRASH"
  else
    ensure_dir "$HOME/.Trash"
    mv "$SESSION_WRAP_DIR" "$SESSION_WRAP_TRASH"
    info "Retired session-wrap recoverably: $SESSION_WRAP_TRASH"
  fi
fi

# Claude marks superseded plugin versions as orphaned but never reclaims them.
# Keep a seven-day grace period so an already-running session can finish using
# its loaded version, then remove only exact-depth cache entries carrying the
# marker Claude wrote itself.
cache_prune_args=(
  --root "$HOME/.claude/plugins/cache"
  --min-age-days 7
)
$DRY_RUN && cache_prune_args+=(--dry-run)
if cache_prune_output=$(python3 "$DOTFILES_DIR/scripts/prune_claude_plugin_cache.py" \
    "${cache_prune_args[@]}"); then
  info "$cache_prune_output"
else
  warn "Could not prune old orphaned Claude plugin caches"
fi

info "Claude Code setup done"
