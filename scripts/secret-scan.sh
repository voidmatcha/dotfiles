#!/bin/bash
set -euo pipefail
# shellcheck disable=SC2034 # consumed by scripts/lib/common.sh after source.
TAG="secret-scan"
# shellcheck source=scripts/lib/common.sh
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

required="${REQUIRE_GITLEAKS:-false}"
case "${1:-}" in
  --required)
    required=true
    ;;
  --optional|"")
    ;;
  -h|--help)
    cat <<'USAGE'
Usage: scripts/secret-scan.sh [--required|--optional]

Runs gitleaks over the current dotfiles working tree and all commits reachable
from local refs. Set GITLEAKS_LOG_OPTS to an explicit narrower git-log range only
when the caller has an authoritative push boundary. In optional mode, a missing
gitleaks binary is reported and skipped. In required mode, a missing dependency
or failed scan exits non-zero.
USAGE
    exit 0
    ;;
  *)
    warn "unknown argument: $1"
    exit 2
    ;;
esac

cd "$DOTFILES_DIR"

if ! command -v gitleaks >/dev/null 2>&1; then
  if $required; then
    error "gitleaks not found; install with ./scripts/brew.sh or brew install gitleaks"
    exit 1
  fi
  warn "gitleaks not found; skipped secret scan (install via Brewfile)"
  exit 0
fi

info "gitleaks working-tree secret scan"
gitleaks detect --source "$DOTFILES_DIR" --config "$DOTFILES_DIR/.gitleaks-worktree.toml" --no-git --redact --verbose

history_log_opts="${GITLEAKS_LOG_OPTS:-}"
if [ -z "$history_log_opts" ]; then
  if ! command -v git >/dev/null 2>&1 || ! git -C "$DOTFILES_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if $required; then
      error "git repository unavailable; cannot verify reachable commit history"
      exit 1
    fi
    warn "git repository unavailable; skipped reachable commit history scan"
    exit 0
  fi

  # Lefthook does not pass the authoritative pre-push stdin ref updates into
  # this helper. A non-checked-out branch or tag can therefore be pushed even
  # when HEAD is clean, so scan every local ref in this small repository.
  history_log_opts="--all"
fi

if [ -n "$history_log_opts" ]; then
  info "gitleaks repository commit-history scan ($history_log_opts)"
  gitleaks git "$DOTFILES_DIR" --config "$DOTFILES_DIR/.gitleaks.toml" --log-opts "$history_log_opts" --redact --verbose
else
  info "gitleaks repository commit-history scan: empty explicit range"
fi
