#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  TMPDIR_TEST="$(mktemp -d)"
  TEST_HOME="$TMPDIR_TEST/home"
  TEST_BIN="$TMPDIR_TEST/bin"
  CALL_LOG="$TMPDIR_TEST/calls.log"
  mkdir -p "$TEST_HOME" "$TEST_BIN"
  : > "$CALL_LOG"
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

write_fake_managers() {
  cat > "$TEST_BIN/brew" <<'SH'
#!/bin/sh
case "$1 $2" in
  "list --formula")
    case "$3" in
      anomalyco/tap/opencode|google-authenticator-libpam|qrencode|starship) exit 0 ;;
      *) exit 1 ;;
    esac
    ;;
  "list --cask")
    case "$3" in
      claude-code|docker|font-meslo-lg-nerd-font|warp) exit 0 ;;
      *) exit 1 ;;
    esac
    ;;
  "uninstall --formula"|"uninstall --cask")
    printf 'brew %s\n' "$*" >> "$CALL_LOG"
    ;;
  "tap ")
    printf '%s\n' anomalyco/tap
    ;;
  "untap anomalyco/tap")
    printf 'brew %s\n' "$*" >> "$CALL_LOG"
    ;;
esac
SH

  cat > "$TEST_BIN/npm" <<'SH'
#!/bin/sh
case "$1" in
  list)
    case "$*" in
      *oh-my-codex*|*oh-my-opencode*|*agent-resumer*) exit 0 ;;
      *) exit 1 ;;
    esac
    ;;
  uninstall) printf 'npm %s\n' "$*" >> "$CALL_LOG" ;;
esac
SH

  cat > "$TEST_BIN/uv" <<'SH'
#!/bin/sh
if [ "$1 $2" = "tool list" ]; then
  printf '%s\n' 'headroom-ai v0.1.0'
elif [ "$1 $2" = "tool uninstall" ]; then
  printf 'uv %s\n' "$*" >> "$CALL_LOG"
fi
SH

  cat > "$TEST_BIN/pipx" <<'SH'
#!/bin/sh
if [ "$1 $2" = "list --short" ]; then
  printf '%s\n' 'headroom-ai 0.1.0'
elif [ "$1" = "uninstall" ]; then
  printf 'pipx %s\n' "$*" >> "$CALL_LOG"
fi
SH

  cat > "$TEST_BIN/launchctl" <<'SH'
#!/bin/sh
printf 'launchctl %s\n' "$*" >> "$CALL_LOG"
SH

  chmod +x "$TEST_BIN/brew" "$TEST_BIN/npm" "$TEST_BIN/uv" \
    "$TEST_BIN/pipx" "$TEST_BIN/launchctl"
}

@test "retirement dry-run is deterministic and executes no package managers" {
  for command_name in brew npm uv pipx launchctl; do
    cat > "$TEST_BIN/$command_name" <<'SH'
#!/bin/sh
printf '%s\n' "unexpected command: $0 $*" >> "$CALL_LOG"
exit 99
SH
    chmod +x "$TEST_BIN/$command_name"
  done

  run env HOME="$TEST_HOME" DOTFILES_DIR="$REPO_ROOT" DRY_RUN=true \
    CALL_LOG="$CALL_LOG" PATH="$TEST_BIN:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/retire.sh"

  [ "$status" -eq 0 ]
  [ ! -s "$CALL_LOG" ]
  [[ "$output" == *"brew uninstall --formula --force anomalyco/tap/opencode"* ]]
  [[ "$output" == *"brew uninstall --cask --force claude-code"* ]]
  [[ "$output" == *"npm uninstall -g oh-my-codex"* ]]
  [[ "$output" == *"uv tool uninstall headroom-ai"* ]]
  [[ "$output" == *"retire managed path"* ]]
}

@test "non-interactive retirement defers Docker when sudo is unavailable" {
  cat > "$TEST_BIN/brew" <<'SH'
#!/bin/sh
if [ "$1 $2 $3" = "list --cask docker" ]; then
  exit 0
fi
if [ "$1 $2" = "uninstall --cask" ]; then
  printf 'brew %s\n' "$*" >> "$CALL_LOG"
fi
exit 1
SH
  cat > "$TEST_BIN/sudo" <<'SH'
#!/bin/sh
exit 1
SH
  chmod +x "$TEST_BIN/brew" "$TEST_BIN/sudo"

  run env HOME="$TEST_HOME" DOTFILES_DIR="$REPO_ROOT" DRY_RUN=false \
    NON_INTERACTIVE=true CALL_LOG="$CALL_LOG" PATH="$TEST_BIN:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/retire.sh"

  [ "$status" -eq 0 ]
  [ ! -s "$CALL_LOG" ]
  [[ "$output" == *"Deferred Homebrew cask requiring interactive sudo: docker"* ]]
}

@test "retirement removes only explicit packages and preserves user OpenCode data" {
  write_fake_managers
  mkdir -p "$TEST_HOME/.config/opencode" "$TEST_HOME/.local/share/opencode" \
    "$TEST_HOME/.local/bin" "$TEST_HOME/.agent-resumer/shims" \
    "$TEST_HOME/Library/LaunchAgents"
  ln -s "$REPO_ROOT/configs/opencode/opencode.json" \
    "$TEST_HOME/.config/opencode/opencode.json"
  ln -s "$REPO_ROOT/configs/AGENTS.md" \
    "$TEST_HOME/.config/opencode/AGENTS.md"
  ln -s "$REPO_ROOT/scripts/headroom-agent.sh" \
    "$TEST_HOME/.local/bin/claudeh"
  printf '%s\n' secret > "$TEST_HOME/.local/share/opencode/auth.json"
  printf '%s\n' mine > "$TEST_HOME/.config/opencode/user-owned.json"
  printf '%s\n' wrapper > "$TEST_HOME/.local/bin/agent-resumer-launch.sh"
  printf '%s\n' plist > "$TEST_HOME/Library/LaunchAgents/com.voidmatcha.agent-resumer.plist"

  run env HOME="$TEST_HOME" DOTFILES_DIR="$REPO_ROOT" DRY_RUN=false \
    CALL_LOG="$CALL_LOG" PATH="$TEST_BIN:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/retire.sh"

  [ "$status" -eq 0 ]
  grep -q '^brew uninstall --formula --force anomalyco/tap/opencode$' "$CALL_LOG"
  grep -q '^brew uninstall --cask --force docker$' "$CALL_LOG"
  grep -q '^brew untap anomalyco/tap$' "$CALL_LOG"
  grep -q '^npm uninstall -g oh-my-codex$' "$CALL_LOG"
  grep -q '^uv tool uninstall headroom-ai$' "$CALL_LOG"
  grep -q '^pipx uninstall headroom-ai$' "$CALL_LOG"
  grep -q '^launchctl bootout gui/.*/com.voidmatcha.agent-resumer$' "$CALL_LOG"
  [ ! -e "$TEST_HOME/.config/opencode/opencode.json" ]
  [ ! -e "$TEST_HOME/.local/bin/claudeh" ]
  [ ! -e "$TEST_HOME/.agent-resumer" ]
  [ -f "$TEST_HOME/.local/share/opencode/auth.json" ]
  [ -f "$TEST_HOME/.config/opencode/user-owned.json" ]
  [ -L "$TEST_HOME/.Trash/dotfiles-retired-tools/.config/opencode/opencode.json" ]
  [ -e "$TEST_HOME/.Trash/dotfiles-retired-tools/.local/bin/agent-resumer-launch.sh" ]
}

@test "retirement checks every nvm npm installation" {
  write_fake_managers
  old_npm="$TEST_HOME/.nvm/versions/node/v20.0.0/bin/npm"
  old_npm_target="$TEST_HOME/.nvm/versions/node/v20.0.0/lib/node_modules/npm/bin/npm-cli.js"
  mkdir -p "$(dirname "$old_npm")" "$(dirname "$old_npm_target")"
  cp "$TEST_BIN/npm" "$old_npm_target"
  ln -s ../lib/node_modules/npm/bin/npm-cli.js "$old_npm"

  run env HOME="$TEST_HOME" DOTFILES_DIR="$REPO_ROOT" DRY_RUN=false \
    CALL_LOG="$CALL_LOG" PATH="$TEST_BIN:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/retire.sh"

  [ "$status" -eq 0 ]
  [ "$(grep -c '^npm uninstall -g oh-my-codex$' "$CALL_LOG")" -eq 2 ]
}

@test "retirement removes only legacy dotfiles links and services" {
  write_fake_managers
  mkdir -p "$TEST_HOME/.claude/commands" "$TEST_HOME/.claude/hooks" \
    "$TEST_HOME/.config/opencode" "$TEST_HOME/.config/ghostty" \
    "$TEST_HOME/.local/bin" "$TEST_HOME/Library/LaunchAgents" \
    "$TEST_HOME/Library/Logs"
  ln -s "$REPO_ROOT/configs/commands/orchestrate.md" \
    "$TEST_HOME/.claude/commands/orchestrate.md"
  ln -s "$REPO_ROOT/configs/hooks/skill-eval.sh" \
    "$TEST_HOME/.claude/hooks/skill-eval.sh"
  ln -s "$REPO_ROOT/configs/hooks/suggest-compact.sh" \
    "$TEST_HOME/.claude/hooks/suggest-compact.sh"
  ln -s "$REPO_ROOT/configs/opencode/plugins" \
    "$TEST_HOME/.config/opencode/plugins"
  ln -s "$REPO_ROOT/configs/ghostty/config" \
    "$TEST_HOME/.config/ghostty/config"
  ln -s "$TMPDIR_TEST/user-owned-orchestrate.md" \
    "$TEST_HOME/.claude/commands/user-owned.md"
  printf '%s\n' wrapper > "$TEST_HOME/.local/bin/opencode-web-launch.sh"
  printf '%s\n' plist > "$TEST_HOME/Library/LaunchAgents/com.user.opencode-web.plist"
  printf '%s\n' plist > "$TEST_HOME/Library/LaunchAgents/com.user.duckdns.plist"
  printf '%s\n' log > "$TEST_HOME/Library/Logs/opencode-web.out.log"
  printf '%s\n' secret > "$TEST_HOME/.opencode-secrets.env"

  run env HOME="$TEST_HOME" DOTFILES_DIR="$REPO_ROOT" DRY_RUN=false \
    CALL_LOG="$CALL_LOG" PATH="$TEST_BIN:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/retire.sh"

  [ "$status" -eq 0 ]
  [ ! -L "$TEST_HOME/.claude/commands/orchestrate.md" ]
  [ ! -L "$TEST_HOME/.claude/hooks/skill-eval.sh" ]
  [ ! -L "$TEST_HOME/.claude/hooks/suggest-compact.sh" ]
  [ ! -L "$TEST_HOME/.config/opencode/plugins" ]
  [ ! -L "$TEST_HOME/.config/ghostty/config" ]
  [ ! -e "$TEST_HOME/.local/bin/opencode-web-launch.sh" ]
  [ ! -e "$TEST_HOME/Library/LaunchAgents/com.user.opencode-web.plist" ]
  [ ! -e "$TEST_HOME/Library/LaunchAgents/com.user.duckdns.plist" ]
  [ ! -e "$TEST_HOME/Library/Logs/opencode-web.out.log" ]
  [ -f "$TEST_HOME/.opencode-secrets.env" ]
  [ -L "$TEST_HOME/.claude/commands/user-owned.md" ]
  [ -L "$TEST_HOME/.Trash/dotfiles-retired-tools/.claude/commands/orchestrate.md" ]
  [ -L "$TEST_HOME/.Trash/dotfiles-retired-tools/.claude/hooks/skill-eval.sh" ]
  [ -L "$TEST_HOME/.Trash/dotfiles-retired-tools/.claude/hooks/suggest-compact.sh" ]
  [ -L "$TEST_HOME/.Trash/dotfiles-retired-tools/.config/opencode/plugins" ]
  [ -L "$TEST_HOME/.Trash/dotfiles-retired-tools/.config/ghostty/config" ]
  grep -q '^launchctl bootout gui/.*/com.user.opencode-web$' "$CALL_LOG"
  grep -q '^launchctl bootout gui/.*/com.user.duckdns$' "$CALL_LOG"
}

@test "retirement ledger excludes current and data-bearing packages" {
  script="$REPO_ROOT/scripts/retire.sh"
  grep -q 'anomalyco/tap/opencode' "$script"
  grep -q 'oh-my-codex' "$script"
  grep -q 'headroom-ai' "$script"
  ! grep -Eq 'RETIRED_BREW_(FORMULAE|CASKS)=.*postgresql' "$script"
  ! grep -q 'brew uninstall.*postgresql' "$script"
  ! grep -q 'brew uninstall.*mosh' "$script"
}

@test "brew setup retires conflicts before applying the current Brewfile" {
  install_brew_line="$(grep -n 'scripts/brew.sh' "$REPO_ROOT/install.sh" | head -1 | cut -d: -f1)"
  retire_line="$(grep -n 'scripts/retire.sh' "$REPO_ROOT/scripts/brew.sh" | head -1 | cut -d: -f1)"
  bundle_line="$(grep -n '^# Run Brewfile' "$REPO_ROOT/scripts/brew.sh" | head -1 | cut -d: -f1)"

  [ -n "$install_brew_line" ]
  [ -n "$retire_line" ]
  [ -n "$bundle_line" ]
  [ "$retire_line" -lt "$bundle_line" ]
}
