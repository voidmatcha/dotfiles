#!/usr/bin/env bash
# tier_check.sh — tiered verification signal; metric = delta vs a captured baseline.
# Usage:
#   tier_check.sh baseline <path> <out.json>      # capture pre-change signal
#   tier_check.sh check    <path> <baseline.json> # compare post-change; verdict to stdout
# T0 (always): lint/syntax on the changed path. T1 (if found): repo test command.
# T2 (behavioral/eval) is repo-specific and handled by the skill loop, not here.
set -uo pipefail

MODE="${1:?baseline|check}"; TARGET="${2:?path}"; REF="${3:?out-or-baseline json}"

# ---- T0: parse/lint errors on the changed path ----
t0_errors() {
  local p="$1" n=0
  case "$p" in
    *.sh)
      command -v bash >/dev/null 2>&1 && { bash -n "$p" 2>/dev/null || n=$((n+1)); }
      command -v shellcheck >/dev/null 2>&1 && { local c; c=$(shellcheck -S error -f gcc "$p" 2>/dev/null | grep -c ': error:' || true); n=$((n+c)); }
      ;;
    *.py)
      command -v ruff >/dev/null 2>&1 && { local c; c=$(ruff check "$p" 2>/dev/null | grep -cE '^[^ ]+:[0-9]+' || true); n=$((n+c)); }
      ;;
    */SKILL.md|SKILL.md)
      grep -q '^name:' "$p" 2>/dev/null || n=$((n+1))
      grep -q '^description:' "$p" 2>/dev/null || n=$((n+1))
      ;;
    *.json)
      if command -v python3 >/dev/null 2>&1; then python3 -c 'import json,sys;json.load(open(sys.argv[1]))' "$p" 2>/dev/null || n=$((n+1)); fi
      ;;
  esac
  printf '%s' "$n"
}

# ---- T1: repo test command discovery (does not run unless RUN_T1=1) ----
t1_cmd() {
  if   [ -x scripts/ci/ci-local.sh ]; then printf 'bash scripts/ci/ci-local.sh --quiet';
  elif [ -f pyproject.toml ] || ls tests/test_*.py >/dev/null 2>&1; then printf 'python -m pytest -q';
  elif [ -f go.mod ]; then printf 'go test ./...';
  elif [ -f package.json ] && command -v jq >/dev/null 2>&1 && jq -e '.scripts.test' package.json >/dev/null 2>&1; then printf 'npm test --silent';
  else printf ''; fi
}

t1_failures() { # runs the test cmd, returns rough failure count (0 = green, 999 = unrun)
  local cmd; cmd=$(t1_cmd)
  [ -z "$cmd" ] && { printf '999'; return; }
  [ "${RUN_T1:-0}" = "1" ] || { printf '999'; return; }
  local out rc
  out=$(eval "$cmd" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then printf '0'; else
    local f; f=$(printf '%s' "$out" | grep -coE '([0-9]+ failed|FAIL|AssertionError)' || true); printf '%s' "$((f>0?f:1))"
  fi
}

snapshot() { printf '{"path":"%s","t0_errors":%s,"t1_failures":%s,"t1_cmd":"%s"}\n' "$TARGET" "$(t0_errors "$TARGET")" "$(t1_failures)" "$(t1_cmd)"; }

case "$MODE" in
  baseline) snapshot > "$REF"; cat "$REF" ;;
  check)
    NOW=$(snapshot)
    getf() { printf '%s' "$1" | python3 -c 'import json,sys;print(json.load(sys.stdin).get(sys.argv[1],0))' "$2" 2>/dev/null || echo 0; }
    b0=$(getf "$(cat "$REF")" t0_errors); n0=$(getf "$NOW" t0_errors)
    b1=$(getf "$(cat "$REF")" t1_failures); n1=$(getf "$NOW" t1_failures)
    verdict=PASS; reason="t0 ${b0}->${n0}, t1 ${b1}->${n1}"
    [ "$n0" -gt "$b0" ] && { verdict=REVERT; reason="T0 regressed ($b0->$n0 lint/syntax errors)"; }
    if [ "$n1" != "999" ] && [ "$b1" != "999" ] && [ "$n1" -gt "$b1" ]; then verdict=REVERT; reason="T1 regressed ($b1->$n1 test failures)"; fi
    printf '{"verdict":"%s","reason":"%s","baseline":%s,"now":%s}\n' "$verdict" "$reason" "$(cat "$REF")" "$NOW"
    [ "$verdict" = PASS ] && exit 0 || exit 1
    ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
