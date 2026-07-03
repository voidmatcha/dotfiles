#!/bin/bash
# purplemux shim — rendered and installed by scripts/services.sh via
# `install -m 755` (same pattern as LaunchAgent wrappers), so the path
# and exec bit are restored on install runs. Do not edit installed copies;
# change this template and re-run services.sh.
#
# Runs purplemux from a source checkout instead of the global npm install. The
# checkout path is rendered at install time from PURPLEMUX_APP_DIR and must live
# OUTSIDE macOS TCC-protected folders (~/Documents, ~/Desktop, ~/Downloads):
# launchd cannot answer the TCC consent prompt, so protected paths hang the
# LaunchAgent instead of failing fast.
set -euo pipefail

APP_DIR="__PURPLEMUX_APP_DIR__"

if [ ! -d "$APP_DIR" ]; then
  echo "[purplemux] source checkout not found: $APP_DIR — re-run services.sh with PURPLEMUX_APP_DIR set, or use npm install -g purplemux" >&2
  exit 78
fi

if [ -f "$APP_DIR/bin/purplemux.js" ]; then
  exec node "$APP_DIR/bin/purplemux.js" "$@"
fi

# Fallback: let node resolve the package entry (package.json "main").
exec node "$APP_DIR" "$@"
