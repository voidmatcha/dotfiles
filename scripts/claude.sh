#!/bin/bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-false}"

GREEN='\033[0;32m'
NC='\033[0m'
info() { echo -e "${GREEN}[claude]${NC} $1"; }

info "Setting up Claude Code..."

# ralph-kage-bunshin
if ! ls ~/.agents/skills/ralph-kage-bunshin-* &>/dev/null 2>&1; then
  if $DRY_RUN; then
    info "[dry-run] npm install -g ralph-kage-bunshin"
  else
    npm install -g ralph-kage-bunshin && info "ralph-kage-bunshin installed" || info "⚠️  ralph-kage-bunshin install failed"
  fi
fi

if $DRY_RUN; then
  info "[dry-run] ralph install-skills"
else
  ralph install-skills && info "ralph install-skills done" || info "⚠️  ralph install-skills failed"
fi

# npm 11.x breaks npx for packages not in package.json
if ! command -v skills &>/dev/null; then
  if $DRY_RUN; then
    info "[dry-run] npm install -g skills"
  else
    npm install -g skills && info "skills CLI installed" || info "⚠️  skills CLI install failed"
  fi
fi

SKILL_REPOS=(
  "dididy/e2e-skills"
  "blader/humanizer"
  "forrestchang/andrej-karpathy-skills"
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
    skills add "$repo" --yes --global 2> >(grep -v "invalid option" >&2) \
      && info "Installed: $repo" \
      || info "⚠️  Failed: $repo"
  fi
done

for url_args in "${SKILL_URLS[@]}"; do
  if $DRY_RUN; then
    info "[dry-run] npx skills add $url_args --yes --global"
  else
    # shellcheck disable=SC2086
    npx skills add $url_args --yes --global 2> >(grep -v "invalid option" >&2) \
      && info "Installed: $url_args" \
      || info "⚠️  Failed: $url_args"
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
    claude plugin install "$plugin" \
      && info "Installed plugin: $plugin" \
      || info "⚠️  Failed plugin: $plugin"
  fi
done

# session-wrap plugin
if ! [ -d ~/.claude/plugins/session-wrap ]; then
  if $DRY_RUN; then
    info "[dry-run] install session-wrap plugin"
  else
    TMPDIR=$(mktemp -d)
    git clone https://github.com/team-attention/plugins-for-claude-natives "$TMPDIR" \
      && cp -r "$TMPDIR/plugins/session-wrap" ~/.claude/plugins/ \
      && info "Installed plugin: session-wrap" \
      || info "⚠️  Failed plugin: session-wrap"
    rm -rf "$TMPDIR"
  fi
else
  info "session-wrap already installed, skipping"
fi

info "Claude Code setup done"
