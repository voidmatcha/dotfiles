#!/bin/bash
set -euo pipefail

# Print one concise label for the current agent surface.
#
# Priority:
#   1. Explicit AGENT_SESSION_LABEL override
#   2. cmux workspace/surface identifiers exported into the terminal
#   3. tmux session/window/pane name
#   4. Agent runtime session IDs
#   5. Current directory basename

max_len="${AGENT_SESSION_LABEL_MAX:-80}"
case "$max_len" in
  ''|*[!0-9]*) max_len=80 ;;
esac

clean_label() {
  local value="$1"
  # Keep status lines compact and single-line. macOS sed/cut are enough here.
  value="$(printf '%s' "$value" | tr '\r\n\t' '   ' | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
  if [ "${#value}" -gt "$max_len" ]; then
    value="${value:0:max_len}"
  fi
  printf '%s\n' "$value"
}

first_env() {
  local name value
  for name in "$@"; do
    value="${!name:-}"
    if [ -n "$value" ]; then
      clean_label "$value"
      return 0
    fi
  done
  return 1
}

short_cmux_part() {
  local value="$1"
  if [[ "$value" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]]; then
    printf '%s\n' "${value:0:8}"
  else
    printf '%s\n' "$value"
  fi
}

if [ -n "${AGENT_SESSION_LABEL:-}" ]; then
  clean_label "$AGENT_SESSION_LABEL"
  exit 0
fi

cmux_workspace="$(first_env CMUX_WORKSPACE_NAME CMUX_WORKSPACE_ID CMUX_WORKSPACE 2>/dev/null || true)"
cmux_surface="$(first_env CMUX_SURFACE_NAME CMUX_SURFACE_ID CMUX_SURFACE 2>/dev/null || true)"
cmux_tab="$(first_env CMUX_TAB_NAME CMUX_TAB_ID CMUX_TAB 2>/dev/null || true)"
cmux_workspace="$(short_cmux_part "$cmux_workspace")"
cmux_surface="$(short_cmux_part "$cmux_surface")"
cmux_tab="$(short_cmux_part "$cmux_tab")"

if [ -n "$cmux_workspace" ] || [ -n "$cmux_surface" ] || [ -n "$cmux_tab" ]; then
  if [ -n "$cmux_workspace" ] && [ -n "$cmux_surface" ]; then
    clean_label "cmux:${cmux_workspace}/${cmux_surface}"
  elif [ -n "$cmux_surface" ]; then
    clean_label "cmux:${cmux_surface}"
  elif [ -n "$cmux_workspace" ]; then
    clean_label "cmux:${cmux_workspace}"
  else
    clean_label "cmux:${cmux_tab}"
  fi
  exit 0
fi

if [ -n "${TMUX:-}" ] && command -v tmux >/dev/null 2>&1; then
  tmux_format="${AGENT_SESSION_LABEL_TMUX_FORMAT:-#S:#W.#P}"
  tmux_label="$(tmux display-message -p "$tmux_format" 2>/dev/null || true)"
  if [ -n "$tmux_label" ]; then
    clean_label "tmux:${tmux_label}"
    exit 0
  fi
fi

if [ -n "${CODEX_SESSION_ID:-}" ]; then
  clean_label "codex:${CODEX_SESSION_ID}"
  exit 0
fi
if [ -n "${CLAUDE_SESSION_ID:-}" ]; then
  clean_label "claude:${CLAUDE_SESSION_ID}"
  exit 0
fi

clean_label "dir:$(basename "${PWD:-$HOME}")"
