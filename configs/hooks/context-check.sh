#!/bin/bash
set -euo pipefail

# Advisory UserPromptSubmit hook for Claude Code. It is cheap and fail-open:
# it tracks idle/turn/prompt/transcript pressure locally and emits additional
# context only when pressure crosses a threshold. Heavy probes live in the
# context-check skill's manual diagnose command.

payload=""
if ! IFS= read -rd '' -t 5 payload; then
  rc=$?
  if [ "$rc" -gt 128 ]; then
    exit 0
  fi
fi

script_path="${BASH_SOURCE[0]}"
if [ -L "$script_path" ]; then
  link_target="$(readlink "$script_path")"
  case "$link_target" in
    /*) script_path="$link_target" ;;
    *) script_path="$(cd "$(dirname "$script_path")" && pwd)/$link_target" ;;
  esac
fi
hook_dir="$(cd "$(dirname "$script_path")" && pwd)"
repo_root="$(cd "$hook_dir/../.." && pwd)"
checker="$repo_root/plugins/local-skills/skills/context-check/scripts/context_check.py"

[ -f "$checker" ] || exit 0
printf '%s' "$payload" | python3 "$checker" hook --cwd "${PWD:-}" || true
