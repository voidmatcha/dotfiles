#!/bin/bash
set -euo pipefail

# LaunchAgent has a minimal PATH. Restore Homebrew, user-local bins, and the
# latest nvm-managed Node bin so npm-installed agent-resumer survives Node
# upgrades better than a hard-coded service path.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.bun/bin:$HOME/.local/bin:/usr/bin:/bin"
if [ -d "$HOME/.nvm/versions/node" ]; then
  # Resolve the highest installed semver (sort -V), not the most recently
  # modified dir (ls -dt). agent-resumer is published per-Node; pinning to the
  # newest version keeps it on the same Node the global npm install targets.
  latest_node="$(find "$HOME/.nvm/versions/node" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort -V | tail -n1 || true)"
  if [ -n "$latest_node" ] && [ -d "$HOME/.nvm/versions/node/$latest_node/bin" ]; then
    export PATH="$HOME/.nvm/versions/node/$latest_node/bin:$PATH"
  fi
fi

if ! command -v agent-resumer >/dev/null 2>&1; then
  echo "[agent-resumer] not found — install with 'npm install -g agent-resumer'" >&2
  exit 78
fi

INTERVAL="${AGENT_RESUMER_INTERVAL:-30000}"
# shellcheck disable=SC2086 # operator-provided extra flags are intentionally word-split.
exec agent-resumer watch --watch --interval "$INTERVAL" --quiet ${AGENT_RESUMER_ARGS:-}
