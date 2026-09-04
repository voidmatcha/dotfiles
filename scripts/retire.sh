#!/bin/bash
set -euo pipefail
# shellcheck disable=SC2034 # consumed by scripts/lib/common.sh after source.
TAG="retire"
# shellcheck source=scripts/lib/common.sh
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

# Append-only retirement ledger for software this repository previously
# installed. Removing an item from the active install list is not enough:
# existing machines must converge too. Keep this list explicit instead of
# calling broad package-manager cleanup commands, which would remove software
# the user installed independently.
RETIRED_BREW_FORMULAE=(
  "anomalyco/tap/opencode"
  "google-authenticator-libpam"
  "qrencode"
  "starship"
)

RETIRED_BREW_CASKS=(
  "claude-code"
  "docker"
  "font-meslo-lg-nerd-font"
  "warp"
)

RETIRED_BREW_TAPS=(
  "anomalyco/tap"
)

RETIRED_NPM_PACKAGES=(
  "agent-resumer"
  "oh-my-codex"
  "oh-my-opencode"
)

RETIRED_UV_TOOLS=(
  "headroom-ai"
)

RETIRED_PIPX_PACKAGES=(
  "headroom-ai"
)

# Deliberately excluded:
# - postgresql: data-bearing major-version migration, never an automatic delete
# - mosh and bats-core: removed temporarily and later restored to the Brewfile
# - OpenCode auth and ~/.opencode-secrets.env: user-owned credentials, not
#   disposable installation state

failure_count=0

record_failure() {
  warn "$1"
  failure_count=$((failure_count + 1))
}

retire_brew_formula() {
  local formula="$1"
  if $DRY_RUN; then
    info "[dry-run] brew uninstall --formula --force $formula"
  elif command -v brew >/dev/null 2>&1 && brew list --formula "$formula" >/dev/null 2>&1; then
    if brew uninstall --formula --force "$formula"; then
      info "Retired Homebrew formula: $formula"
    else
      record_failure "Could not retire Homebrew formula: $formula"
    fi
  fi
}

retire_brew_cask() {
  local cask="$1"
  if $DRY_RUN; then
    info "[dry-run] brew uninstall --cask --force $cask"
  elif command -v brew >/dev/null 2>&1 && brew list --cask "$cask" >/dev/null 2>&1; then
    # Docker's cask uninstall removes privileged helpers. A background or
    # non-interactive updater cannot satisfy that password prompt and Homebrew
    # may partially mutate the cask before failing, so defer it atomically.
    if [ "$cask" = "docker" ] \
        && ! sudo_ok "brew uninstall --cask --force $cask"; then
      warn "Deferred Homebrew cask requiring interactive sudo: $cask"
      return 0
    fi
    if brew uninstall --cask --force "$cask"; then
      info "Retired Homebrew cask: $cask"
    else
      record_failure "Could not retire Homebrew cask: $cask"
    fi
  fi
}

retire_brew_tap() {
  local tap="$1"
  if $DRY_RUN; then
    info "[dry-run] brew untap $tap"
  elif command -v brew >/dev/null 2>&1 && brew tap | grep -Fxq "$tap"; then
    # A user may have installed a different formula from the old tap. Homebrew
    # refuses the untap in that case; preserve it without failing the update.
    if brew untap "$tap"; then
      info "Retired Homebrew tap: $tap"
    else
      warn "Kept Homebrew tap still used by another installed formula: $tap"
    fi
  fi
}

retire_npm_package_with() {
  local npm_bin="$1"
  local package="$2"
  if "$npm_bin" list -g --depth=0 "$package" >/dev/null 2>&1; then
    if "$npm_bin" uninstall -g "$package"; then
      info "Retired npm package via $npm_bin: $package"
    else
      record_failure "Could not retire npm package via $npm_bin: $package"
    fi
  fi
}

retire_npm_packages() {
  local package npm_bin
  local npm_bins=""

  if $DRY_RUN; then
    for package in "${RETIRED_NPM_PACKAGES[@]}"; do
      info "[dry-run] npm uninstall -g $package (current npm and every NVM installation)"
    done
    return 0
  fi

  npm_bins="$({
    command -v npm 2>/dev/null || true
    if [ -d "$HOME/.nvm/versions/node" ]; then
      find "$HOME/.nvm/versions/node" -mindepth 3 -maxdepth 3 -path '*/bin/npm' -print 2>/dev/null || true
    fi
  } | awk 'NF && !seen[$0]++')"

  [ -n "$npm_bins" ] || return 0
  while IFS= read -r npm_bin; do
    [ -x "$npm_bin" ] || continue
    for package in "${RETIRED_NPM_PACKAGES[@]}"; do
      retire_npm_package_with "$npm_bin" "$package"
    done
  done <<< "$npm_bins"
}

retire_uv_tool() {
  local package="$1"
  if $DRY_RUN; then
    info "[dry-run] uv tool uninstall $package"
  elif command -v uv >/dev/null 2>&1 \
      && uv tool list 2>/dev/null | awk -v wanted="$package" '$1 == wanted { found=1 } END { exit !found }'; then
    if uv tool uninstall "$package"; then
      info "Retired uv tool: $package"
    else
      record_failure "Could not retire uv tool: $package"
    fi
  fi
}

retire_pipx_package() {
  local package="$1"
  if $DRY_RUN; then
    info "[dry-run] pipx uninstall $package"
  elif command -v pipx >/dev/null 2>&1 \
      && pipx list --short 2>/dev/null | awk -v wanted="$package" '$1 == wanted { found=1 } END { exit !found }'; then
    if pipx uninstall "$package"; then
      info "Retired pipx package: $package"
    else
      record_failure "Could not retire pipx package: $package"
    fi
  fi
}

retire_path() {
  local path="$1"
  local relative destination
  relative="${path#"$HOME"/}"
  destination="$HOME/.Trash/dotfiles-retired-tools/$relative"

  if $DRY_RUN; then
    info "[dry-run] retire managed path $path -> $destination"
    return 0
  fi
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    return 0
  fi
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    destination="$(next_backup_path "$destination")"
  fi
  mkdir -p "$(dirname "$destination")"
  mv "$path" "$destination"
  info "Retired managed path recoverably: $path -> $destination"
}

retire_managed_symlink() {
  local path="$1"
  local target_suffix="$2"
  local target

  if $DRY_RUN; then
    retire_path "$path"
    return 0
  fi
  [ -L "$path" ] || return 0
  target="$(readlink "$path")"
  case "$target" in
    *"$target_suffix") retire_path "$path" ;;
    *) warn "Preserved non-dotfiles symlink at retired path: $path -> $target" ;;
  esac
}

retire_launch_agent() {
  local label="$1"
  local plist="$HOME/Library/LaunchAgents/$label.plist"

  if $DRY_RUN; then
    info "[dry-run] launchctl bootout gui/$(id -u)/$label"
  elif command -v launchctl >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
  fi
  retire_path "$plist"
}

info "Reconciling explicitly retired dotfiles-managed tools..."

for item in "${RETIRED_BREW_FORMULAE[@]}"; do
  retire_brew_formula "$item"
done
for item in "${RETIRED_BREW_CASKS[@]}"; do
  retire_brew_cask "$item"
done
for item in "${RETIRED_BREW_TAPS[@]}"; do
  retire_brew_tap "$item"
done

retire_npm_packages
for item in "${RETIRED_UV_TOOLS[@]}"; do
  retire_uv_tool "$item"
done
for item in "${RETIRED_PIPX_PACKAGES[@]}"; do
  retire_pipx_package "$item"
done

retire_launch_agent "com.voidmatcha.agent-resumer"
retire_launch_agent "com.user.opencode-web"
retire_launch_agent "com.user.duckdns"
retire_path "$HOME/.local/bin/agent-resumer-launch.sh"
retire_path "$HOME/.local/bin/opencode-web-launch.sh"
retire_path "$HOME/.agent-resumer"
retire_path "$HOME/.local/state/headroom-agent"
retire_path "$HOME/Library/Logs/agent-resumer.out.log"
retire_path "$HOME/Library/Logs/agent-resumer.err.log"
retire_path "$HOME/Library/Logs/opencode-web.out.log"
retire_path "$HOME/Library/Logs/opencode-web.err.log"

for wrapper in headroom-agent claudeh codexh omxh; do
  retire_managed_symlink "$HOME/.local/bin/$wrapper" "/scripts/headroom-agent.sh"
done
retire_managed_symlink "$HOME/.config/opencode/opencode.json" "/configs/opencode/opencode.json"
retire_managed_symlink "$HOME/.config/opencode/oh-my-openagent.json" "/configs/opencode/oh-my-openagent.json"
retire_managed_symlink "$HOME/.config/opencode/AGENTS.md" "/configs/AGENTS.md"
retire_managed_symlink "$HOME/.config/opencode/plugins" "/configs/opencode/plugins"
retire_managed_symlink "$HOME/.config/ghostty/config" "/configs/ghostty/config"
retire_managed_symlink "$HOME/.claude/commands/orchestrate.md" "/configs/commands/orchestrate.md"
retire_managed_symlink "$HOME/.claude/hooks/skill-eval.sh" "/configs/hooks/skill-eval.sh"
retire_managed_symlink "$HOME/.claude/hooks/suggest-compact.sh" "/configs/hooks/suggest-compact.sh"

if [ "$failure_count" -ne 0 ]; then
  error "Retirement completed with $failure_count failure(s)"
  exit 1
fi

info "Retired tool reconciliation done"
