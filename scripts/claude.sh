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
# inspected first. Idempotent: if claude already exists we just check for an
# update; otherwise we run the installer (defaults to the stable channel).
install_claude_code() {
  if command -v claude &>/dev/null; then
    info "claude present ($(claude --version 2>/dev/null | awk '{print $1}')) — checking for updates"
    if $DRY_RUN; then
      info "[dry-run] claude update"
    else
      with_timeout 120 claude update </dev/null \
        || warn "claude update failed/timed out (continuing with the installed build)"
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

# npm 11.x breaks npx for packages not in package.json
if ! command -v skills &>/dev/null; then
  if $DRY_RUN; then
    info "[dry-run] npm install -g skills"
  else
    if npm install -g skills; then
      info "skills CLI installed"
    else
      info "⚠️  skills CLI install failed"
    fi
  fi
fi

SKILL_REPOS=(
  "voidmatcha/e2e-skills"
  # voidmatcha/ui-clone-skills: handled separately below via the upstream
  # install.sh — the `skills add` path skips required system tooling
  # (uv, ffmpeg, imagemagick, dssim, agent-browser) and the ui_clone/
  # Python package, both of which the skill's preflight checks expect.
  "blader/humanizer"
  "epoko77-ai/im-not-ai"
  "forrestchang/andrej-karpathy-skills@karpathy-guidelines"
  # obra/superpowers: removed — already installed via `superpowers@claude-plugins-official`
  # plugin (which pins to a tested sha, more stable than tracking main).
  # vercel-labs/agent-skills currently publishes PromptScript skills (Vercel
  # patterns, deploy, optimization, and writing/design guidelines). The skills
  # CLI rejects PromptScript global installs, so keep this repo out of the
  # global bootstrap loop. Also keep the CLI target pinned to Claude Code below:
  # when `--global --yes` is used without `--agent`, skills CLI auto-expands
  # universal `.agents/skills` targets and currently includes PromptScript, which
  # is project-only.
  "anthropics/skills@doc-coauthoring"        # handover docs / specs
  "anthropics/skills@internal-comms"         # status reports / FAQs
  "anthropics/skills@webapp-testing"         # cake-pc-web Playwright
  "anthropics/skills@mcp-builder"            # author new MCP servers
  "anthropics/skills@skill-creator"          # author / tune custom skills
  # supercent-io/skills-template: removed — repository deleted/private on GitHub
  # (clone now fails with auth prompt). Built-in /code-review and
  # /security-review cover the same ground.
  # yeachan-heo/oh-my-claudecode@project-session-manager and @ai-slop-cleaner
  # are PromptScript skills. The skills CLI rejects PromptScript global
  # installs, so keep them out of the global SKILL_REPOS bootstrap path.
)

SKILL_URLS=(
  # pbakaus/impeccable and kepano/obsidian-skills currently publish
  # PromptScript skills. The skills CLI rejects PromptScript global installs,
  # so do not feed them to the global `skills add --global` loop.
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

if [ "${#SKILL_URLS[@]}" -gt 0 ]; then
  for url_args in "${SKILL_URLS[@]}"; do
    if $DRY_RUN; then
      info "[dry-run] npx skills add $url_args --yes --global --agent claude-code"
    else
      # shellcheck disable=SC2086
      # url_args intentionally stores pre-tokenized flags.
      if npx skills add $url_args --yes --global --agent claude-code 2> >(grep -v "invalid option" >&2); then
        info "Installed: $url_args"
      else
        info "⚠️  Failed: $url_args"
      fi
    fi
  done
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
    if "$UI_CLONE_DIR/install.sh" ${ui_clone_flags[@]+"${ui_clone_flags[@]}"}; then
      info "ui-clone-skills: install.sh OK — run '/plugin install ui-clone-skills@voidmatcha' inside Claude Code to activate"
    else
      warn "ui-clone-skills: install.sh exited non-zero"
    fi
  fi
  remove_tracked_claude_local_marketplace
fi

PLUGIN_MARKETPLACES=(
  "openai/codex-plugin-cc"
  # jarrodwatts/claude-hud — native statusline HUD for context/tool/agent/todo
  # visibility. Requires one-time `/claude-hud:setup` to write statusLine.
  "jarrodwatts/claude-hud"
  # khendzel/skills-janitor — cross-scope skill hygiene report/fix/value tools
  # for Claude Code + Codex skill installs.
  "khendzel/skills-janitor"
  # wshobson/agents — 80+ focused plugins (185 agents, 153 skills, 100 commands)
  # registered under the marketplace id `claude-code-workflows`.
  # Catalog: https://github.com/wshobson/agents/blob/main/docs/plugins.md
  "wshobson/agents"
  # thedotmack/claude-mem — persistent memory + cross-session search (~75k★).
  # Hooks SessionStart/End + 5 others, SQLite + Chroma vector DB, MCP search tools,
  # web viewer at localhost:37777, <private> tag for sensitive content.
  "thedotmack/claude-mem"
  # uditgoenka/autoresearch — Claude-native autonomous metric loop
  # (`/autoresearch`, `/autoresearch:debug`, `/autoresearch:fix`, etc.).
  "uditgoenka/autoresearch"
  # hamelsmu/claude-review-loop — Claude implements, Codex reviews, Claude fixes.
  # We set REVIEW_LOOP_CODEX_FLAGS in settings to avoid the plugin's dangerous
  # default `--dangerously-bypass-approvals-and-sandbox`.
  "hamelsmu/claude-review-loop"
)

PLUGINS=(
  "ralph-loop@claude-plugins-official"
  "autoresearch@autoresearch"                         # bounded metric loop + 13 Claude commands
  "claude-hud@claude-hud"                             # statusline context/tool/agent/todo HUD
  "skills-janitor@skills-janitor"                     # skill inventory, dupes, token value
  "superpowers@claude-plugins-official"
  "frontend-design@claude-plugins-official"
  "rust-analyzer-lsp@claude-plugins-official"
  "fakechat@claude-plugins-official"
  "vercel@claude-plugins-official"
  "session-report@claude-plugins-official"
  "claude-md-management@claude-plugins-official"
  "hookify@claude-plugins-official"
  "security-guidance@claude-plugins-official"         # edit/stop security review hooks + agent
  "review-loop@hamel-review"                          # explicit /review-loop Claude→Codex loop

  # wshobson/agents — one plugin per role. Each is isolated (own agents +
  # commands + skills); only what you install is loaded into context.
  "comprehensive-review@claude-code-workflows"          # architect + code-review + security
  "javascript-typescript@claude-code-workflows"         # cake-pc-web stack
  "python-development@claude-code-workflows"
  "frontend-mobile-development@claude-code-workflows"
  "security-scanning@claude-code-workflows"             # SAST
  "documentation-generation@claude-code-workflows"      # OpenAPI / mermaid / tutorials
  "unit-testing@claude-code-workflows"                  # pytest + jest generators
  "git-pr-workflows@claude-code-workflows"
  "tdd-workflows@claude-code-workflows"                 # test-first methodology
  "error-debugging@claude-code-workflows"               # error analysis + trace debugging
  "ui-design@claude-code-workflows"                     # iOS/Android/RN/web UI guidance
  "accessibility-compliance@claude-code-workflows"      # WCAG auditing
  "content-marketing@claude-code-workflows"
  "seo-content-creation@claude-code-workflows"
  "seo-technical-optimization@claude-code-workflows"    # meta tags, schema markup
  "seo-analysis-monitoring@claude-code-workflows"

  # thedotmack/claude-mem — persistent memory across sessions
  "claude-mem@thedotmack"
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
# shellcheck disable=SC2016 # jq variables are passed via --arg.
INSTALLED_PLUGIN_FILTER='.plugins | has($p)'

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
  if ! command -v jq &>/dev/null || ! command -v envsubst &>/dev/null || ! command -v claude &>/dev/null; then
    warn "jq, envsubst, or claude not available — cannot register MCPs from $mcp_file"
    return 1
  fi

  # Load dev/user secrets so any ${VAR} placeholders in mcp.json expand below.
  # ~/.dev.secrets.env is gitignored (*.secrets.env in .gitignore).
  # Public mcp.json currently has no ${VAR} placeholders, but this keeps the
  # door open for adding entries that need keys later without code changes.
  if [ -f "$HOME/.dev.secrets.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$HOME/.dev.secrets.env"
    set +a
  fi

  local names registration_failed=0
  local envsubst_allowlist
  # shellcheck disable=SC2016 # envsubst receives a variable allowlist.
  envsubst_allowlist='${EXA_API_KEY} ${FIGMA_API_KEY}'
  names=$(jq -r '.mcpServers | keys[]' "$mcp_file" 2>/dev/null)
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    local raw_entry entry placeholder_names placeholder_name placeholder_value
    local missing_placeholders old_entry install_status rollback_status
    # Use --arg to safely pass the key (avoids jq filter string-interpolation injection).
    # Refuse to render when a referenced variable is unset/empty. Rendering an
    # empty secret and removing the old entry first destroys a working config.
    # Extend the allowlist as new keys are added to mcp.json.
    raw_entry=$(jq -c --arg n "$name" '.mcpServers[$n]' "$mcp_file")
    if ! printf '%s' "$raw_entry" | jq -e 'type == "object"' >/dev/null 2>&1; then
      warn "Invalid MCP $name: entry must be a JSON object (keeping existing config)"
      registration_failed=1
      continue
    fi
    # `envsubst --variables` recognizes both $VAR and ${VAR} forms without
    # expanding values, so missing unbraced secrets cannot collapse to "".
    placeholder_names=$(envsubst --variables "$raw_entry" | sort -u)
    missing_placeholders=""
    while IFS= read -r placeholder_name; do
      [ -z "$placeholder_name" ] && continue
      placeholder_value="${!placeholder_name-}"
      if [ -z "$placeholder_value" ]; then
        if [ -n "$missing_placeholders" ]; then
          missing_placeholders="$missing_placeholders, $placeholder_name"
        else
          missing_placeholders="$placeholder_name"
        fi
      fi
    done <<< "$placeholder_names"
    if [ -n "$missing_placeholders" ]; then
      warn "Skipping MCP $name: missing environment placeholder(s): $missing_placeholders (keeping existing config)"
      continue
    fi

    entry=$(printf '%s' "$raw_entry" | envsubst "$envsubst_allowlist")
    if printf '%s' "$entry" | grep -Eq '\$\{?[A-Za-z_][A-Za-z0-9_]*\}?'; then
      warn "Skipping MCP $name: unresolved environment placeholder remains (keeping existing config)"
      continue
    fi
    if ! printf '%s' "$entry" | jq -e . >/dev/null 2>&1; then
      warn "Skipping MCP $name: rendered entry is invalid JSON (keeping existing config)"
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
      # add-json receives rendered secrets. Never echo its diagnostics because
      # a failing CLI may print the full rejected argument back to the caller.
      warn "Failed to register MCP: $name (exit $install_status; CLI output suppressed to protect rendered secrets)"
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
          warn "CRITICAL: MCP rollback failed verification for $name (exit $rollback_status; CLI output suppressed to protect rendered secrets)"
        fi
      else
        # No prior entry existed, so remove any unverified partial registration.
        with_timeout 30 claude mcp remove --scope user "$name" >/dev/null 2>&1 || true
      fi
    fi
  done <<< "$names"

  return "$registration_failed"
}

info "Registering user-scope MCP servers from configs/mcp.json..."
register_mcp_from_file "$DOTFILES_DIR/configs/mcp.json"

# session-wrap plugin — pinned SHA prevents silent main-branch breakage
SESSION_WRAP_SHA="fd9c20754dba0b0ab040f3f2cd2cb533fc43347d"  # 2026-05-20, checked via gh api
SESSION_WRAP_DIR="$HOME/.claude/plugins/session-wrap"
if ! [ -d "$SESSION_WRAP_DIR" ]; then
  if $DRY_RUN; then
    info "[dry-run] install session-wrap plugin (SHA: $SESSION_WRAP_SHA)"
  else
    TMPDIR=$(mktemp -d)
    if git clone https://github.com/team-attention/plugins-for-claude-natives "$TMPDIR" \
      && git -C "$TMPDIR" checkout "$SESSION_WRAP_SHA" \
      && cp -r "$TMPDIR/plugins/session-wrap" "$SESSION_WRAP_DIR"; then
      info "Installed plugin: session-wrap ($SESSION_WRAP_SHA)"
    else
      info "⚠️  Failed plugin: session-wrap"
    fi
    rm -rf "$TMPDIR"
  fi
else
  info "session-wrap already installed, skipping"
fi

info "Claude Code setup done"
