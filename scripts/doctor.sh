#!/bin/bash
set -euo pipefail
# shellcheck disable=SC2034 # consumed by scripts/lib/common.sh after source.
TAG="doctor"
# shellcheck source=scripts/lib/common.sh
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

cd "$DOTFILES_DIR"

status_ok=0
status_warn=0
status_fail=0

ok() { status_ok=$((status_ok + 1)); printf 'ok    %s\n' "$*"; }
warn_check() { status_warn=$((status_warn + 1)); printf 'warn  %s\n' "$*"; }
fail_check() { status_fail=$((status_fail + 1)); printf 'fail  %s\n' "$*"; }

check_command() {
  local name="$1" command_name="$2" required="${3:-required}"
  if command -v "$command_name" >/dev/null 2>&1; then
    ok "$name: $(command -v "$command_name")"
  elif [ "$required" = "optional" ]; then
    warn_check "$name missing (optional)"
  else
    fail_check "$name missing"
  fi
}

check_symlink() {
  local label="$1" expected="$2" actual="$3"
  if [ -L "$actual" ] && [ "$(readlink "$actual")" = "$expected" ]; then
    ok "$label linked"
  elif [ -e "$actual" ] || [ -L "$actual" ]; then
    warn_check "$label points elsewhere: $actual -> $(readlink "$actual" 2>/dev/null || printf 'real file')"
  else
    warn_check "$label missing: $actual"
  fi
}

check_git_state() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local dirty_count
    dirty_count="$(git status --porcelain | wc -l | tr -d ' ')"
    if [ "$dirty_count" = "0" ]; then
      ok "git working tree clean"
    else
      warn_check "git working tree has $dirty_count change(s)"
    fi
  else
    fail_check "not inside a git working tree"
  fi
}

check_lefthook() {
  if ! command -v lefthook >/dev/null 2>&1; then
    fail_check "lefthook missing"
    return
  fi
  ok "lefthook: $(lefthook version 2>/dev/null || printf 'installed')"
  if [ -x .git/hooks/pre-push ] && grep -q 'lefthook' .git/hooks/pre-push 2>/dev/null; then
    ok "lefthook pre-push hook installed"
  else
    warn_check "lefthook pre-push hook not installed; run lefthook install"
  fi
}

check_headroom() {
  local port="${HEADROOM_PORT:-8787}"
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "http://127.0.0.1:$port/livez" >/dev/null 2>&1; then
    ok "Headroom proxy live on :$port"
  else
    warn_check "Headroom proxy not live on :$port (ok when wrappers are unused)"
  fi
}

case "${1:-}" in
  ""|--summary)
    ;;
  -h|--help)
    cat <<'USAGE'
Usage: scripts/doctor.sh [--summary]

Advisory dotfiles health snapshot. It does not mutate the machine and exits
non-zero only for failed required checks, not for warnings.
USAGE
    exit 0
    ;;
  *)
    warn "unknown argument: $1"
    exit 2
    ;;
esac

info "dotfiles health snapshot"
check_git_state

check_command "git" git
check_command "brew" brew
check_command "bats" bats optional
check_command "gitleaks" gitleaks optional
check_command "zsh" zsh
check_lefthook

if [ -x /Library/Developer/CommandLineTools/usr/libexec/git-core/git-credential-osxkeychain ]; then
  ok "Apple CLT git-credential-osxkeychain available"
else
  warn_check "Apple CLT git-credential-osxkeychain missing"
fi

check_symlink "HOME/.zshrc" "$DOTFILES_DIR/configs/.zshrc" "$HOME/.zshrc"
check_symlink "HOME/.tmux.conf" "$DOTFILES_DIR/configs/.tmux.conf" "$HOME/.tmux.conf"
check_symlink "HOME/.gitconfig" "$DOTFILES_DIR/configs/.gitconfig" "$HOME/.gitconfig"
check_symlink "HOME/.gitignore_global" "$DOTFILES_DIR/configs/.gitignore_global" "$HOME/.gitignore_global"
check_symlink "HOME/.agent/AGENTS.md" "$DOTFILES_DIR/configs/AGENTS.md" "$HOME/.agent/AGENTS.md"

check_headroom

printf '\nsummary: %s ok, %s warn, %s fail\n' "$status_ok" "$status_warn" "$status_fail"
[ "$status_fail" -eq 0 ]
