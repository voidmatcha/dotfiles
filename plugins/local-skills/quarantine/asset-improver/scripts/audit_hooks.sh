#!/usr/bin/env bash
# audit_hooks.sh — lint a hook or script asset and emit findings as "[severity] path: message"
# (mirrors skills-janitor's output contract so findings merge with /janitor-report).
# severity in: error | warn | info. Generic across repos; external tools are optional.
set -uo pipefail

TARGET="${1:?usage: audit_hooks.sh <path-to-.sh-or-hooks.json>}"
finding() { printf '[%s] %s: %s\n' "$1" "$TARGET" "$2"; }

if [ ! -e "$TARGET" ]; then finding error "file does not exist"; exit 0; fi

case "$TARGET" in
  *.json)
    # Hook manifest: must be valid JSON.
    if command -v jq >/dev/null 2>&1; then
      jq -e . "$TARGET" >/dev/null 2>&1 || finding error "invalid JSON (jq parse failed)"
    elif command -v python3 >/dev/null 2>&1; then
      python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$TARGET" 2>/dev/null \
        || finding error "invalid JSON (python parse failed)"
    else
      finding info "no jq/python3 to validate JSON"
    fi
    # Best-effort: hook commands without a timeout can hang the host.
    if command -v jq >/dev/null 2>&1 && jq -e . "$TARGET" >/dev/null 2>&1; then
      n=$(jq '[.. | objects | select(has("command")) | select(has("timeout")|not)] | length' "$TARGET" 2>/dev/null || echo 0)
      [ "${n:-0}" -gt 0 ] && finding warn "$n hook command(s) declare no timeout (can hang the host)"
    fi
    ;;
  *.sh)
    # Shell asset: shebang, strict mode, syntax, shellcheck.
    head -n1 "$TARGET" | grep -Eq '^#!.*(bash|sh)\b' || finding warn "missing or non-shell shebang"
    if ! grep -Eq 'set -[eu]|set -o (errexit|nounset|pipefail)' "$TARGET"; then
      finding warn "no 'set -euo pipefail' (or equivalent) — errors may pass silently"
    fi
    if command -v bash >/dev/null 2>&1; then
      err=$(bash -n "$TARGET" 2>&1) || finding error "syntax error: ${err##*: }"
    fi
    if command -v shellcheck >/dev/null 2>&1; then
      while IFS= read -r line; do
        [ -n "$line" ] && finding warn "shellcheck: $line"
      done < <(shellcheck -S error -f gcc "$TARGET" 2>/dev/null | sed 's/^[^:]*:[0-9]*:[0-9]*: //' | sort -u | head -10)
    else
      finding info "shellcheck not installed — static analysis skipped"
    fi
    ;;
  *.py)
    # Python helper/script: syntax + lint.
    if command -v python3 >/dev/null 2>&1; then
      err=$(python3 -m py_compile "$TARGET" 2>&1) || finding error "python syntax error: ${err##*: }"
    fi
    if command -v ruff >/dev/null 2>&1; then
      while IFS= read -r line; do
        [ -n "$line" ] && finding warn "ruff: $line"
      done < <(ruff check "$TARGET" 2>/dev/null | sed 's/^[^ ]*:[0-9]*:[0-9]*: //' | sort -u | head -10)
    else
      finding info "ruff not installed — python lint skipped"
    fi
    ;;
  *)
    finding info "unhandled asset type (expected *.sh, *.py, or *.json)"
    ;;
esac

exit 0
