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

    # Treat grouping and command-substitution delimiters as command boundaries
    # too. This is deliberately conservative: the guard protects the command
    # string, not only syntax that a full shell parser can prove executable.
    def command_segments(value):
        return re.split(r'\s*(?:&&|\|\||;|\||&|\n|\(|\)|\{|\}|`)\s*', value)

    def segment_tokens(segment):
        try:
            return shlex.split(segment)
        except ValueError:
            return []

    def embedded_shell_commands(tokens):
        shells = {'bash', 'dash', 'ksh', 'sh', 'zsh'}
        for index, token in enumerate(tokens):
            command = token.rsplit('/', 1)[-1]
            if command == 'eval' and index + 1 < len(tokens):
                yield ' '.join(tokens[index + 1:])
                continue
            if command not in shells:
                continue
            for option_index in range(index + 1, len(tokens) - 1):
                option = tokens[option_index]
                if (option == '-c' or
                        (option.startswith('-') and
                         not option.startswith('--') and
                         'c' in option[1:])):
                    yield tokens[option_index + 1]
                    break

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

    pending_segments = command_segments(command)
    inspected_segments = 0
    while pending_segments:
        segment = pending_segments.pop(0)
        inspected_segments += 1
        if inspected_segments > 64:
            deny('Blocked risky Bash command: nested shell command is too complex')

        tokens = segment_tokens(segment)
        if not tokens:
            continue

        pending_segments.extend(
            nested
            for embedded in embedded_shell_commands(tokens)
            for nested in command_segments(embedded)
        )

        # Inspect every suffix rather than only tokens[0]. Shell control words,
        # wrappers, and assignments can otherwise hide the guarded command.
        for token_index in range(len(tokens)):
            candidate = tokens[token_index:]

            if len(candidate) >= 2 and candidate[0] == 'git' and candidate[1] == 'push':
                rest = candidate[2:]

                # `-f` also arrives bundled, as in `git push -uf origin`.
                def is_short_force(token):
                    return (token.startswith('-') and not token.startswith('--')
                            and 'f' in token[1:])

                if any(token == '--force' or is_short_force(token)
                       or token.startswith('+') for token in rest):
                    deny('Blocked risky Bash command: force push')
                # --force-with-lease is allowed (it fails if the remote ref moved),
                # except toward protected branches.
                if any(token.startswith('--force-with-lease') for token in rest):
                    protected = {'main', 'master'}
                    def lease_target(token):
                        if token.startswith('--force-with-lease='):
                            return token.split('=', 1)[1].split(':', 1)[0].split('/')[-1]
                        return None
                    operands = [token for token in rest if not token.startswith('-')]
                    # With no refspec git pushes the current branch, which the hook
                    # cannot see. `git push --force-with-lease origin` on main read
                    # as an unprotected push because only `origin` was inspected.
                    if len(operands) < 2:
                        deny('Blocked risky Bash command: lease push without an '
                             'explicit refspec - name the branch')
                    for token in rest:
                        ref = token.split(':', 1)[-1].split('/')[-1] if not token.startswith('-') else lease_target(token)
                        if ref in protected:
                            deny('Blocked risky Bash command: force push to protected branch')

            if candidate[0] == 'rm':
                flags = ''.join(token[1:] for token in candidate[1:] if token.startswith('-') and token != '--')
                if 'r' in flags and 'f' in flags:
                    if any(target in {'/', '~'} or target.startswith('/*') for target in rm_targets(candidate)):
                        deny('Blocked risky Bash command: root rm -rf')

            if candidate[0] in read_commands and any(is_dotenv_token(token) for token in candidate[1:]):
                deny('Blocked risky Bash command: dotenv read')

    deny_patterns = [
        ('git reset --hard', re.compile(r'\bgit\s+reset\s+--hard\b')),
        ('shell pipe from network', re.compile(r'\b(?:curl|wget)\b[^\n|]*\|\s*(?:/usr/bin/|/bin/)?(?:sh|bash)\b')),
    ]

    for reason, pattern in deny_patterns:
        if pattern.search(command):
            deny(f'Blocked risky Bash command: {reason}')
PY
