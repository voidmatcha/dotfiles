#!/bin/bash
set -euo pipefail

# LaunchAgent has a minimal PATH; restore tmux + node + the global npm bin dir.
# nvm installs Node under ~/.nvm/versions/node/<ver>/bin — we resolve the latest
# installed version at runtime so this keeps working across Node upgrades.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if [ -d "$HOME/.nvm/versions/node" ]; then
  latest_node="$(find "$HOME/.nvm/versions/node" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort -V | tail -n1 || true)"
  if [ -n "$latest_node" ] && [ -d "$HOME/.nvm/versions/node/$latest_node/bin" ]; then
    export PATH="$HOME/.nvm/versions/node/$latest_node/bin:$PATH"
  fi
fi

if ! command -v purplemux >/dev/null 2>&1; then
  echo "[purplemux] purplemux not found in PATH — install with 'npm install -g purplemux'" >&2
  exit 78
fi

# purplemux listens on :8022. services.sh exposes it through Tailscale Serve:
# tailscale serve --bg --https=443 --set-path=/ http://localhost:8022
exec purplemux
