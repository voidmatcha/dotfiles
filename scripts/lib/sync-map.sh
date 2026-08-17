#!/bin/bash
# Decide which changes require a restart.
#
# This is the quietest failure point in the repo. claude-mem sitting two months
# behind also came down to "it updated but never took effect". Install success
# and the change taking effect are different things, and no script knew the
# difference.
#
# Nothing is killed automatically. An agent session cut off mid-work cannot be
# recovered. This only reports; the human decides.

restart_note_for_path() {
  local path="$1"
  case "$path" in
    configs/claude-settings.json|configs/hooks/*|configs/CLAUDE.md|configs/RTK.md)
      printf 'Claude Code 재시작 필요 (설정과 훅은 세션 시작 시 로드된다)\n' ;;
    configs/codex/*)
      printf 'Codex 재시작 필요\n' ;;
    scripts/claude.sh)
      printf 'Claude Code 재시작 필요 (플러그인 버전이 바뀌었을 수 있다)\n' ;;
    scripts/skills.sh|plugins/local-skills/*)
      printf '스킬 변경은 새 세션부터 반영된다\n' ;;
    scripts/services.sh)
      printf 'launchd 재로드 확인 필요\n' ;;
    configs/.zshrc|configs/.tmux.conf)
      printf '새 셸 또는 tmux 세션 필요\n' ;;
  esac
}

# Collect the items that need a restart since the last commit.
restart_notes_since() {
  local baseline="$1" path note
  git -C "$DOTFILES_DIR" diff --name-only "$baseline..HEAD" 2>/dev/null | while read -r path; do
    [ -z "$path" ] && continue
    note="$(restart_note_for_path "$path")"
    [ -n "$note" ] && printf '%s\n' "$note"
  done | sort -u
}
