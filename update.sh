#!/bin/bash
# Root-level entry point, for parity with ./install.sh.
# The logic lives in scripts/update.sh (which sources scripts/lib/common.sh):
#   ./update.sh            git pull + install.sh --upgrade (setup + version bumps)
#   ./update.sh --check    preview only; change nothing
#   ./update.sh --no-pull  skip the git pull step
exec "$(cd "$(dirname "$0")" && pwd)/scripts/update.sh" "$@"
