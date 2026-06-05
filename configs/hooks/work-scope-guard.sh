#!/bin/bash
set -euo pipefail

# Advisory SessionStart hook. Emits extra context only when the session cwd is
# under a configured work root. Fail open: never block Claude Code startup.

payload=""
if ! IFS= read -rd '' -t 5 payload; then
  rc=$?
  if [ "$rc" -gt 128 ]; then
    exit 0
  fi
fi

python3 - "$payload" <<'PY'
import json
import os
import sys
from pathlib import Path

raw = sys.argv[1] if len(sys.argv) > 1 else ""
payload = {}
if raw:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            payload = parsed
    except json.JSONDecodeError:
        payload = {}

cwd = payload.get("cwd") or os.environ.get("PWD") or ""
event = payload.get("hook_event_name") or "SessionStart"
if not cwd:
    raise SystemExit(0)

home = Path.home()
roots_env = os.environ.get("WORK_SCOPE_GUARD_ROOTS", "")
roots = [Path(value).expanduser() for value in roots_env.split(":") if value]
if not roots:
    roots = [home / "work"]

try:
    cwd_path = Path(cwd).expanduser().resolve()
except OSError:
    cwd_path = Path(cwd).expanduser()

matched = None
for root in roots:
    try:
        root_path = root.resolve()
    except OSError:
        root_path = root
    try:
        cwd_path.relative_to(root_path)
        matched = root_path
        break
    except ValueError:
        continue

if not matched:
    raise SystemExit(0)

msg = (
    "WORK-SCOPE GUARD: this session is under a configured work root "
    f"({matched}). Treat internal URLs, private repos, customer data, and secrets as sensitive. "
    "Use local/authenticated tools for sensitive pages; do not route internal URLs through hosted readers/search. "
    "Keep company-specific hooks, tokens, emails, and hostnames out of public dotfiles."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": msg,
    }
}, separators=(",", ":")))
PY
