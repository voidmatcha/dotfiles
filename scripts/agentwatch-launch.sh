#!/bin/bash
set -euo pipefail

# bun is a stable Homebrew-managed runtime (/opt/homebrew/bin), and
# `bun install -g` places agentwatch at a single stable bin
# (~/.bun/bin/agentwatch). Running under bun avoids nvm's per-Node-version
# global-bin fragility. npm-installed fallbacks are searched only from stable
# launchd-safe paths.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.bun/bin:$HOME/.local/bin:/usr/bin:/bin"

AW=""
if [ -x "$HOME/.bun/bin/agentwatch" ]; then
  AW="$HOME/.bun/bin/agentwatch"
elif command -v agentwatch >/dev/null 2>&1; then
  AW="$(command -v agentwatch)"
fi

if [ -z "$AW" ]; then
  echo "[agentwatch] agentwatch not found — install with 'bun install -g @voidmatcha/agentwatch'" >&2
  exit 78
fi

# Supervise loop cadence/flags.
# AGENTWATCH_ARGS is intentionally word-split so operators can pass flags.
INTERVAL="${AGENTWATCH_INTERVAL:-30000}"
# shellcheck disable=SC2086
if command -v bun >/dev/null 2>&1; then
  exec bun "$AW" watch --watch --interval "$INTERVAL" ${AGENTWATCH_ARGS:-}
else
  exec "$AW" watch --watch --interval "$INTERVAL" ${AGENTWATCH_ARGS:-}
fi
