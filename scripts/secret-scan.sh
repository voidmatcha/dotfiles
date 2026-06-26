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

Runs gitleaks over the current dotfiles working tree. In optional mode, a
missing gitleaks binary is reported and skipped. In required mode, missing
or failing gitleaks exits non-zero; use this from git hooks.
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
gitleaks detect --source "$DOTFILES_DIR" --no-git --redact --verbose
