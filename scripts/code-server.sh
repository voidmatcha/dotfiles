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
  local -a install_args
  if $DRY_RUN; then
    for ext in "${CODE_SERVER_EXTENSIONS[@]}"; do
      if $UPGRADE; then
        info "[dry-run] code-server --install-extension $ext --force"
      else
        info "[dry-run] code-server --install-extension $ext"
      fi
    done
    return 0
  fi

  if ! command -v code-server >/dev/null 2>&1; then
    warn "code-server not found; skipping browser IDE extensions"
    return 0
  fi

  for ext in "${CODE_SERVER_EXTENSIONS[@]}"; do
    install_args=(--install-extension "$ext")
    if $UPGRADE; then
      install_args+=(--force)
    fi
    info "Installing code-server extension: $ext"
    with_timeout 90 code-server "${install_args[@]}" \
      || warn "code-server extension install failed: $ext"
  done
}

install_code_server_extensions
info "code-server worktree extensions checked"
