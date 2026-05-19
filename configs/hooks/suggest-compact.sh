#!/bin/bash
# PreToolUse hook — advisory only, never blocks.
#
# Counts tool calls per session in a tmp file keyed by $CLAUDE_SESSION_ID
# and emits a stderr hint at 50/100/150/200 calls so the user can /compact
# at a natural break point rather than letting auto-compact wipe context
# mid-task.
#
# Cheap (~one stat + one read + one write per tool call). Always exit 0;
# this hook NEVER blocks a tool call — Claude treats non-zero exit from
# advisory hooks as an error.

set -eu

# Drain stdin with a bounded read so we don't hang on a stuck pipe. We
# don't actually need the payload — we count any tool call regardless.
# bash builtin avoids the macOS-no-`timeout(1)` portability trap.
IFS= read -rd '' -t 1 _drain 2>/dev/null || true

session_id="${CLAUDE_SESSION_ID:-default}"
count_file="${TMPDIR:-/tmp}/claude-tool-count-${session_id}"

prev=$(cat "$count_file" 2>/dev/null || echo 0)
case "$prev" in
  ''|*[!0-9]*) prev=0 ;;
esac
count=$((prev + 1))
printf '%d' "$count" > "$count_file"

case "$count" in
  50|100|150|200|300|400)
    echo "suggest-compact: ~${count} tool calls this session — consider /compact at the next natural break" >&2
    ;;
esac

exit 0
