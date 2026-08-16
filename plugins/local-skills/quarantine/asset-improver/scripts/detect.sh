#!/usr/bin/env bash
# detect.sh — emit a TSV manifest of improvable assets in a repo: "type<TAB>path".
# Types: skill | hook | script. Considers tracked files when in a git repo, else falls
# back to a bounded find. Excludes this skill's own directory and common vendor dirs.
set -euo pipefail

ROOT="${1:-$PWD}"
SELF_DIR_NAME="asset-improver"
# Self-exclusion is anchored at start OR after a slash, so asset-improver is skipped even when the
# scan root IS the skills dir (path has no leading slash before the skill name).
EXCLUDE_RE='(^|/)(\.git|node_modules|\.venv|venv|dist|build|vendor|tmp|scratch|\.handover)(/|$)|(^|/)'"$SELF_DIR_NAME"'/'

cd "$ROOT"

# Prefer tracked files; fall back to find for non-git or untracked trees.
list_files() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files -z
  else
    find . -type f -not -path '*/.git/*' -print0
  fi
}

emit() { # type, path
  printf '%s\t%s\n' "$1" "$2"
}

while IFS= read -r -d '' f; do
  f="${f#./}"
  printf '%s' "$f" | grep -Eq "$EXCLUDE_RE" && continue
  case "$f" in
    */SKILL.md|SKILL.md)                     emit skill  "$f" ;;
    hooks*.json|*/hooks*.json)               emit hook   "$f" ;;
    hooks/*.sh|*/hooks/*.sh)                 emit hook   "$f" ;;
    *.sh|*.py)                               emit script "$f" ;;
  esac
done < <(list_files)
