#!/bin/bash
set -euo pipefail

# LaunchAgent has a minimal PATH; restore tailscale (~/.local/bin) and opencode (/opt/homebrew/bin).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Refuse to source the secrets file unless it is chmod 600 and owned by us —
# prevents secret leakage to other local processes / mistaken loose perms.
SECRETS_FILE="$HOME/.opencode-secrets.env"
if [ -f "$SECRETS_FILE" ]; then
  perms=$(stat -f '%Lp' "$SECRETS_FILE")
  owner=$(stat -f '%u' "$SECRETS_FILE")
  if [ "$perms" != "600" ] || [ "$owner" != "$(id -u)" ]; then
    echo "[opencode-web] refusing to source $SECRETS_FILE (perms=$perms owner=$owner)" >&2
    echo "[opencode-web] expected: chmod 600, owned by uid=$(id -u)" >&2
    exit 78
  fi
  set -a
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
  set +a
fi

HOST="127.0.0.1"
for _ in {1..30}; do
  if ts_ip="$(tailscale ip -4 2>/dev/null | head -n1)" && [ -n "$ts_ip" ]; then
    HOST="$ts_ip"
    break
  fi
  sleep 1
done

exec opencode web --hostname "$HOST" --port 4096
