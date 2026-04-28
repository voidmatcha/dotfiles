#!/bin/bash
set -euo pipefail
TAG="claude"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

info "Setting up Claude Code..."

# ralph-kage-bunshin
if ! ls ~/.agents/skills/ralph-kage-bunshin-* &>/dev/null 2>&1; then
  if $DRY_RUN; then
    info "[dry-run] npm install -g ralph-kage-bunshin"
  else
    if npm install -g ralph-kage-bunshin; then
      info "ralph-kage-bunshin installed"
    else
      info "⚠️  ralph-kage-bunshin install failed"
    fi
  fi
fi

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
  "dididy/e2e-skills"
  "dididy/ui-skills"
  "blader/humanizer"
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

PLUGINS=(
  "ralph-loop@claude-plugins-official"
)

info "Installing Claude Code Plugins..."

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
