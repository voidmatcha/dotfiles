#!/bin/bash
# 재시작이 필요한 변경을 판별한다.
#
# 이 저장소에서 가장 조용히 실패하는 자리다. claude-mem 이 두 달 밀려 있던 것도
# 결국 "업데이트는 됐는데 적용이 안 됨"이었다. 설치 성공과 반영 완료는 다르고,
# 그 차이를 아는 스크립트가 없었다.
#
# 자동으로 죽이지 않는다. 작업 중인 에이전트 세션이 끊기면 되돌릴 수 없다.
# 보고만 하고 사람이 결정한다.

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

# 마지막 커밋 이후 재시작이 필요한 항목을 모은다.
restart_notes_since() {
  local baseline="$1" path note
  git -C "$DOTFILES_DIR" diff --name-only "$baseline..HEAD" 2>/dev/null | while read -r path; do
    [ -z "$path" ] && continue
    note="$(restart_note_for_path "$path")"
    [ -n "$note" ] && printf '%s\n' "$note"
  done | sort -u
}
