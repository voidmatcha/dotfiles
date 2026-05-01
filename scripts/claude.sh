#!/bin/bash
set -euo pipefail
TAG="claude"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

info "Setting up Claude Code..."

if $DRY_RUN; then
  info "[dry-run] ralph install-skills"
else
  if ralph install-skills; then
    info "ralph install-skills done"
  else
    info "⚠️  ralph install-skills failed"
  fi
fi

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
  "voidmatcha/ui-clone-skills"
  "blader/humanizer"
  "epoko77-ai/im-not-ai"
  "forrestchang/andrej-karpathy-skills@karpathy-guidelines"
  "obra/superpowers"
  "vercel-labs/agent-skills"
  "anthropics/skills@frontend-design"
  "supercent-io/skills-template@security-best-practices"
  "supercent-io/skills-template@code-review"
  "yeachan-heo/oh-my-claudecode@ultrawork"
)

SKILL_URLS=(
  "https://github.com/pbakaus/impeccable --skill clarify"
)

for repo in "${SKILL_REPOS[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] skills add $repo --yes --global"
  else
    if skills add "$repo" --yes --global 2> >(grep -v "invalid option" >&2); then
      info "Installed: $repo"
    else
      info "⚠️  Failed: $repo"
    fi
  fi
done

for url_args in "${SKILL_URLS[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] npx skills add $url_args --yes --global"
  else
    # shellcheck disable=SC2086
    # url_args intentionally stores pre-tokenized flags.
    if npx skills add $url_args --yes --global 2> >(grep -v "invalid option" >&2); then
      info "Installed: $url_args"
    else
      info "⚠️  Failed: $url_args"
    fi
  fi
done

PLUGIN_MARKETPLACES=(
  "openai/codex-plugin-cc"
)

PLUGINS=(
  "ralph-loop@claude-plugins-official"
  "codex@openai-codex"
)

info "Installing Claude Code Plugins..."

for marketplace in "${PLUGIN_MARKETPLACES[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] claude plugin marketplace add $marketplace"
  else
    if claude plugin marketplace add "$marketplace"; then
      info "Added marketplace: $marketplace"
    else
      info "⚠️  Failed marketplace: $marketplace"
    fi
  fi
done

for plugin in "${PLUGINS[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] claude plugin install $plugin"
  else
    if claude plugin install "$plugin"; then
      info "Installed plugin: $plugin"
    else
      info "⚠️  Failed plugin: $plugin"
    fi
  fi
done

# Codex CLI is required by codex@openai-codex; install if missing.
if ! command -v codex >/dev/null 2>&1; then
  if $DRY_RUN; then
    info "[dry-run] npm install -g @openai/codex"
  else
    if npm install -g @openai/codex; then
      info "Codex CLI installed"
    else
      info "⚠️  Codex CLI install failed"
    fi
  fi
fi

# session-wrap plugin
if ! [ -d ~/.claude/plugins/session-wrap ]; then
  if $DRY_RUN; then
    info "[dry-run] install session-wrap plugin"
  else
    TMPDIR=$(mktemp -d)
    if git clone https://github.com/team-attention/plugins-for-claude-natives "$TMPDIR" \
      && cp -r "$TMPDIR/plugins/session-wrap" ~/.claude/plugins/; then
      info "Installed plugin: session-wrap"
    else
      info "⚠️  Failed plugin: session-wrap"
    fi
    rm -rf "$TMPDIR"
  fi
else
  info "session-wrap already installed, skipping"
fi

info "Claude Code setup done"
