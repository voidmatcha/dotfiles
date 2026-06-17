#!/bin/bash
set -euo pipefail

# `caffeinate` is built into macOS (/usr/bin/caffeinate). The default `-s`
# prevents system sleep only on AC power. The assertion exists only while this
# process runs; unloading the LaunchAgent fully reverts it. It does not keep a
# laptop awake with the lid closed.
CAFFEINATE_BIN="/usr/bin/caffeinate"
if [ ! -x "$CAFFEINATE_BIN" ]; then
  echo "[caffeinate] $CAFFEINATE_BIN not found" >&2
  exit 78
fi

# CAFFEINATE_ARGS is intentionally word-split so operators can pass flags.
# shellcheck disable=SC2086
exec "$CAFFEINATE_BIN" ${CAFFEINATE_ARGS:--s}
