#!/bin/sh
# llmwiki UserPromptSubmit: record only the moments where cwd changed (spec 5.7).
#
# fail-open: a missing or broken llmwiki must never block the session. But it
# must not die quietly either — failures land in the log, where doctor's
# llmwiki-hook check reads them. Dump errors to /dev/null and a hook can sit
# idle for months with nobody noticing. This repo already lost two months of
# Codex history that way.
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
# The hooks run in a login shell environment. There python3 is
# /usr/bin/python3 (3.9), which has no tomllib, so every call that reads the
# config dies. That actually happened - because the hooks fail open the session
# stayed fine, while cwd recording had stopped entirely. The plists already had
# this resolution for the same reason; only the hooks were missing it.
py=
# The candidate list has to be swappable by tests. Absolute paths are mixed in,
# so a test that only empties PATH never reaches this branch and ends up
# verifying something other than what its name says.
# The default list must keep its quotes. Inside ${VAR:-...} it is word-split
# after expansion, so on a HOME containing a space the pyenv candidate breaks
# into two pieces. A later candidate does catch it, but that is luck, not
# design. Split only when an override is set - that value comes from tests,
# where a space is the separator.
if [ -n "${LLMWIKI_PYTHON_CANDIDATES:-}" ]; then
  # shellcheck disable=SC2086  # the override is split on purpose
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
# No usable python still does not block the session. Just record that fact.
if [ -z "$py" ]; then
  printf '%s\tUserPromptSubmit\tno python3 with tomllib (needs 3.11+)\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log/hook-errors.log" 2>/dev/null
  exit 0
fi

if ! err=$("$py" -m scripts.llmwiki hook-user-prompt 2>&1 >&3); then
  printf '%s\tUserPromptSubmit\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$err" >> "$log/hook-errors.log" 2>/dev/null
fi 3>&1
exit 0
