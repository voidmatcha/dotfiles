#!/bin/bash
set -euo pipefail

resolve_script_dir() {
  local source dir target
  source="${BASH_SOURCE[0]}"
  while [ -L "$source" ]; do
    dir="$(cd -P "$(dirname "$source")" && pwd)"
    target="$(readlink "$source")"
    if [[ "$target" == /* ]]; then
      source="$target"
    else
      source="$dir/$target"
    fi
  done
  cd -P "$(dirname "$source")" && pwd
}

script_dir="$(resolve_script_dir)"
label_script="${AGENT_SESSION_LABEL_COMMAND:-$script_dir/agent-session-label.sh}"
worktree_script="${AGENT_WORKTREE_LINK_COMMAND:-}"
self_path="$script_dir/claude-statusline.sh"
label=""
worktree_link=""
base_out=""

if [ -x "$label_script" ]; then
  label="$($label_script 2>/dev/null || true)"
fi

if [ "${AGENT_STATUSLINE_WORKTREE_LINK:-1}" != "0" ] && [ -x "$worktree_script" ]; then
  worktree_link="$($worktree_script --link 2>/dev/null || true)"
fi

run_base_statusline() {
  local candidate
  for candidate in \
    "${AGENT_STATUSLINE_BASE:-}" \
    "$HOME/.claude/statusline-original.sh"
  do
    [ -n "$candidate" ] || continue
    [ "$candidate" != "$self_path" ] || continue
    [ -x "$candidate" ] || continue
    "$candidate" "$@"
    return $?
  done
  return 0
}

base_out="$(run_base_statusline "$@" || true)"

prefix=""
if [ -n "$label" ]; then
  prefix="[$label]"
fi
if [ -n "$worktree_link" ]; then
  if [ -n "$prefix" ]; then
    prefix="$prefix [$worktree_link]"
  else
    prefix="[$worktree_link]"
  fi
fi

if [ -n "$base_out" ]; then
  first=1
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$first" -eq 1 ]; then
      if [ -n "$prefix" ]; then
        printf '%s %s\n' "$prefix" "$line"
      else
        printf '%s\n' "$line"
      fi
      first=0
    else
      printf '%s\n' "$line"
    fi
  done <<< "$base_out"
elif [ -n "$prefix" ]; then
  printf '%s\n' "$prefix"
fi
