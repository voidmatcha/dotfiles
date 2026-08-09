#!/bin/sh
# llmwiki SessionStart: 세션 이름이 태스크 ID면 자동 바인딩하고 열린 태스크를 주입한다.
#
# fail-open: llmwiki 가 없거나 깨져도 세션을 절대 막지 않는다. 다만 조용히
# 죽지는 않는다 — 실패는 로그에 남고 doctor 의 llmwiki-hook 검사가 읽는다.
# 오류를 /dev/null 로 버리면 훅이 몇 달을 놀아도 아무도 모른다. 이 저장소는
# 이미 그 방식으로 Codex 기록을 두 달 잃었다.
DOTFILES_DIR="${DOTFILES_DIR:-$(
  for l in "$HOME/.zshrc" "$HOME/.agent/AGENTS.md" "$HOME/.claude/settings.json"; do
    t=$(readlink "$l" 2>/dev/null) || continue
    r=$(cd "$(dirname "$t")/.." 2>/dev/null && pwd) || continue
    [ -d "$r/scripts" ] && printf '%s' "$r" && break
  done
)}"
[ -n "$DOTFILES_DIR" ] || exit 0
cd "$DOTFILES_DIR" 2>/dev/null || exit 0

log="${XDG_STATE_HOME:-$HOME/.local/state}/llmwiki"
mkdir -p "$log" 2>/dev/null
# 훅은 로그인 셸 환경에서 돈다. 거기서 python3 는 /usr/bin/python3(3.9)이라
# tomllib 이 없고, 설정을 읽는 모든 호출이 죽는다. 실제로 그렇게 됐다 -
# fail-open 이라 세션은 멀쩡했지만 cwd 기록이 통째로 멈춰 있었다. plist 는
# 같은 이유로 이미 이 해결을 갖고 있었는데 훅만 빠져 있었다.
py=
# 후보 목록은 테스트가 갈아끼울 수 있어야 한다. 절대경로가 섞여 있어서
# PATH 만 비우는 테스트는 이 분기에 닿지 못하고, 이름과 다른 것을
# 검증하게 된다.
# 기본 목록은 따옴표를 지켜야 한다. ${VAR:-...} 안에 두면 확장 후 단어
# 분리되어, 공백이 든 HOME 에서 pyenv 후보가 두 조각으로 쪼개진다. 뒤
# 후보가 받아주긴 하지만 그건 우연이지 설계가 아니다. 오버라이드가 있을
# 때만 분리한다 - 그쪽은 테스트가 넘기는 값이라 공백이 구분자다.
if [ -n "${LLMWIKI_PYTHON_CANDIDATES:-}" ]; then
  # shellcheck disable=SC2086  # 오버라이드는 의도적으로 분리한다
  set -- $LLMWIKI_PYTHON_CANDIDATES
else
  set -- "$HOME/.pyenv/shims/python3" /opt/homebrew/bin/python3 \
         /usr/local/bin/python3 python3
fi
for c in "$@"; do
  command -v "$c" >/dev/null 2>&1 || continue
  "$c" -c "import tomllib" >/dev/null 2>&1 || continue
  py="$c"; break
done
# 쓸 수 있는 파이썬이 없어도 세션은 막지 않는다. 그 사실만 남긴다.
if [ -z "$py" ]; then
  printf '%s\tSessionStart\tno python3 with tomllib (needs 3.11+)\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log/hook-errors.log" 2>/dev/null
  exit 0
fi

if ! err=$("$py" -m scripts.llmwiki hook-session-start 2>&1 >&3); then
  printf '%s\tSessionStart\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$err" >> "$log/hook-errors.log" 2>/dev/null
fi 3>&1
exit 0
