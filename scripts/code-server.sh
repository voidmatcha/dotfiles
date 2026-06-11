#!/bin/bash
set -euo pipefail

TAG="code-server"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

CODE_SERVER_EXTENSIONS=(
  "jackiotyu.git-worktree-manager"
  "eamodio.gitlens"
  "mhutchie.git-graph"
)

install_code_server_extensions() {
  local ext
  if $DRY_RUN; then
    for ext in "${CODE_SERVER_EXTENSIONS[@]}"; do
      info "[dry-run] code-server --install-extension $ext"
    done
    return 0
  fi

  if ! command -v code-server >/dev/null 2>&1; then
    warn "code-server not found; skipping browser IDE extensions"
    return 0
  fi

  for ext in "${CODE_SERVER_EXTENSIONS[@]}"; do
    info "Installing code-server extension: $ext"
    with_timeout 90 code-server --install-extension "$ext" \
      || warn "code-server extension install failed: $ext"
  done
}

install_code_server_extensions
info "code-server worktree extensions checked"
