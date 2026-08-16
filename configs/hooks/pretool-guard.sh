#!/bin/bash
set -euo pipefail

# Read hook payload from stdin with a 5s timeout. Claude Code has had reports
# of stdin not being closed (issues #240, #459) which would hang bash hooks
# forever. We use bash builtin `read -t` rather than coreutils `timeout(1)`
# because the latter isn't on stock macOS. On EOF (success path for hook
# input) `read -rd ''` exits non-zero but payload still contains the data;
# on timeout the exit code is >128 and payload is empty/partial.
payload=""
if ! IFS= read -rd '' -t 5 payload; then
  rc=$?
  if [ "$rc" -gt 128 ]; then
    echo "pretool-guard: stdin read timed out after 5s — allowing tool call" >&2
    exit 0
  fi
fi
if [ -z "$payload" ]; then
  echo "pretool-guard: empty stdin — allowing tool call" >&2
  exit 0
fi

python3 - "$payload" <<'PY'
import json
import re
import shlex
import sys

def deny(reason):
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        }
    }, separators=(',', ':')))
    sys.exit(0)

try:
    payload = json.loads(sys.argv[1] or '{}')
except json.JSONDecodeError:
    deny('malformed hook input')

if not isinstance(payload, dict):
    deny('malformed hook input')

if payload.get('hook_event_name') != 'PreToolUse':
    sys.exit(0)

tool_name = payload.get('tool_name')
if tool_name != 'Bash':
    sys.exit(0)

tool_input = payload.get('tool_input') or {}
if not isinstance(tool_input, dict):
    deny(f'malformed {tool_name} tool input')

if tool_name == 'Bash':
    command = tool_input.get('command', '')
    if not isinstance(command, str):
        deny('malformed Bash command')

    def command_segments(value):
        return re.split(r'\s*(?:&&|\|\||;)\s*', value)

    def segment_tokens(segment):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return []

        while tokens and tokens[0] in {'sudo', 'command'}:
            tokens = tokens[1:]
        return tokens

    def rm_targets(tokens):
        targets = []
        parsing_options = True
        for token in tokens[1:]:
            if parsing_options and token == '--':
                parsing_options = False
                continue
            if parsing_options and token.startswith('-'):
                continue
            parsing_options = False
            targets.append(token)
        return targets

    def is_dotenv_token(token):
        return token == '.env' or token.startswith('.env.') or '/.env' in token or token.endswith('.secrets.env')

    read_commands = {
        'awk', 'cat', 'cp', 'grep', 'head', 'less', 'more', 'node', 'perl',
        'python', 'python3', 'rg', 'ruby', 'rsync', 'scp', 'sed', 'tail',
    }

    for segment in command_segments(command):
        tokens = segment_tokens(segment)
        if not tokens:
            continue

        if len(tokens) >= 2 and tokens[0] == 'git' and tokens[1] == 'push':
            rest = tokens[2:]
            if any(token in {'-f', '--force'} or token.startswith('+') for token in rest):
                deny('Blocked risky Bash command: force push')
            # --force-with-lease is allowed (fails if the remote ref moved),
            # except toward protected branches.
            if any(token.startswith('--force-with-lease') for token in rest):
                protected = {'main', 'master'}
                def lease_target(token):
                    if token.startswith('--force-with-lease='):
                        return token.split('=', 1)[1].split(':', 1)[0].split('/')[-1]
                    return None
                for token in rest:
                    ref = token.split(':', 1)[-1].split('/')[-1] if not token.startswith('-') else lease_target(token)
                    if ref in protected:
                        deny('Blocked risky Bash command: force push to protected branch')

        if tokens[0] == 'rm':
            flags = ''.join(token[1:] for token in tokens[1:] if token.startswith('-') and token != '--')
            if 'r' in flags and 'f' in flags:
                if any(target in {'/', '~'} or target.startswith('/*') for target in rm_targets(tokens)):
                    deny('Blocked risky Bash command: root rm -rf')

        if tokens[0] in read_commands and any(is_dotenv_token(token) for token in tokens[1:]):
            deny('Blocked risky Bash command: dotenv read')

    deny_patterns = [
        ('git reset --hard', re.compile(r'\bgit\s+reset\s+--hard\b')),
        ('shell pipe from network', re.compile(r'\b(?:curl|wget)\b[^\n|]*\|\s*(?:/usr/bin/|/bin/)?(?:sh|bash)\b')),
    ]

    for reason, pattern in deny_patterns:
        if pattern.search(command):
            deny(f'Blocked risky Bash command: {reason}')
PY
