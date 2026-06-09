#!/bin/bash
set -euo pipefail
# shellcheck disable=SC2034 # consumed by scripts/lib/common.sh after source.
TAG="verify"
# shellcheck source=scripts/lib/common.sh
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

mode="full"
case "${1:-}" in
  --quick|quick)
    mode="quick"
    ;;
  --full|full|"")
    mode="full"
    ;;
  -h|--help)
    cat <<'USAGE'
Usage: scripts/verify.sh [--quick|--full]

--quick  shell syntax, JSON/TOML/plist parsing, plugin manifests, diff whitespace
--full   quick checks plus Bats when available (default)
USAGE
    exit 0
    ;;
  *)
    warn "unknown argument: $1"
    exit 2
    ;;
esac

cd "$DOTFILES_DIR"

info "shell syntax"
while IFS= read -r file; do
  bash -n "$file"
done < <(find scripts install.sh bootstrap.sh configs/hooks -type f -name '*.sh' | sort)

if command -v zsh &>/dev/null && [ -f configs/.zshrc ]; then
  zsh -n configs/.zshrc
fi

info "Python syntax"
python_cache_dir="$(mktemp -d)"
while IFS= read -r file; do
  PYTHONPYCACHEPREFIX="$python_cache_dir" python3 -m py_compile "$file"
done < <(find scripts plugins/local-skills/skills -type f -name '*.py' | sort)
rm -rf "$python_cache_dir"

info "JSON manifests/configs"
python3 - <<'PY'
import json
from pathlib import Path

roots = [Path('configs'), Path('.claude-plugin'), Path('.agents/plugins'), Path('plugins/local-skills')]
files = []
for root in roots:
    if root.exists():
        files.extend(sorted(root.rglob('*.json')))
for path in files:
    json.loads(path.read_text())
print(f'validated {len(files)} JSON file(s)')
PY

info "TOML config"
python3 - <<'PY'
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - old local Python fallback
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None


def strip_comment(line):
    in_string = False
    quote = ""
    escaped = False
    out = []
    for char in line:
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            continue
        if char in {'"', "'"}:
            in_string = True
            quote = char
            out.append(char)
        elif char == "#":
            break
        else:
            out.append(char)
    return "".join(out).strip()


def validate_toml_minimal(text, path):
    """Dependency-free sanity check for this repo's portable Codex TOML.

    Strict tomllib/tomli is preferred. This fallback covers the syntax used in
    configs/codex/config.toml so macOS system Python can run the verifier
    without installing extra packages.
    """
    import ast
    import re

    key_re = re.compile(r'^(?:[A-Za-z0-9_.-]+|"[^"\\]*(?:\\.[^"\\]*)*")$')
    header_re = re.compile(r'^\[[A-Za-z0-9_.-]+\]$')
    current = ""
    start_line = 0
    bracket_balance = 0
    saw_assignment = False

    def check_statement(statement, line_no):
        nonlocal saw_assignment
        if not statement:
            return
        if statement.startswith("["):
            if not header_re.match(statement):
                raise SyntaxError(f"{path}:{line_no}: invalid TOML table header: {statement}")
            return
        if "=" not in statement:
            raise SyntaxError(f"{path}:{line_no}: expected key = value")
        key, value = statement.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key_re.match(key):
            raise SyntaxError(f"{path}:{line_no}: invalid TOML key: {key}")
        if not value:
            raise SyntaxError(f"{path}:{line_no}: missing TOML value for {key}")
        if value in {"true", "false"}:
            saw_assignment = True
            return
        if re.fullmatch(r"[0-9]+", value):
            saw_assignment = True
            return
        if value.startswith("["):
            if not value.endswith("]"):
                raise SyntaxError(f"{path}:{line_no}: unterminated TOML array")
            ast.literal_eval(value)
            saw_assignment = True
            return
        if value.startswith('"') or value.startswith("'"):
            ast.literal_eval(value)
            saw_assignment = True
            return
        raise SyntaxError(f"{path}:{line_no}: unsupported TOML value in fallback parser: {value}")

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line)
        if not line:
            continue
        if current:
            current += "\n" + line
            bracket_balance += line.count("[") - line.count("]")
            if bracket_balance <= 0:
                check_statement(current, start_line)
                current = ""
            continue
        if "=" in line:
            value = line.split("=", 1)[1].strip()
            bracket_balance = value.count("[") - value.count("]")
            if bracket_balance > 0:
                current = line
                start_line = line_no
                continue
        check_statement(line, line_no)
    if current:
        raise SyntaxError(f"{path}:{start_line}: unterminated TOML array")
    if not saw_assignment:
        raise SyntaxError(f"{path}: no TOML assignments found")


path = Path('configs/codex/config.toml')
if path.exists():
    text = path.read_text()
    if tomllib is not None:
        tomllib.loads(text)
        print(f'validated {path}')
    else:
        validate_toml_minimal(text, path)
        print(f'validated {path} (minimal fallback)')
PY

if command -v plutil &>/dev/null; then
  info "plist files"
  while IFS= read -r file; do
    plutil -lint "$file" >/dev/null
  done < <(find . -type f -name '*.plist' -not -path './.git/*' | sort)
fi

info "plugin manifests"
python3 - <<'PY'
import json
from pathlib import Path

required = [
    Path('.claude-plugin/marketplace.json'),
    Path('.agents/plugins/marketplace.json'),
    Path('plugins/local-skills/.claude-plugin/plugin.json'),
    Path('plugins/local-skills/.codex-plugin/plugin.json'),
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit('missing plugin manifest(s): ' + ', '.join(missing))

claude_market = json.loads(Path('.claude-plugin/marketplace.json').read_text())
codex_market = json.loads(Path('.agents/plugins/marketplace.json').read_text())
claude = json.loads(Path('plugins/local-skills/.claude-plugin/plugin.json').read_text())
codex = json.loads(Path('plugins/local-skills/.codex-plugin/plugin.json').read_text())
assert claude_market['name'] == 'dotfiles-local'
assert claude_market['plugins'][0]['name'] == 'local-skills'
assert claude_market['plugins'][0]['source'] == './plugins/local-skills'
assert codex_market['plugins'][0]['name'] == 'local-skills'
assert codex_market['plugins'][0]['source'] == {'source': 'local', 'path': './plugins/local-skills'}
assert claude['name'] == 'local-skills'
assert claude.get('skills') == './skills/'
assert codex['name'] == 'local-skills'
assert codex.get('skills') == './skills/'
assert Path('plugins/local-skills/skills/dotfiles-verify/SKILL.md').exists()
print('validated local-skills plugin manifests')
PY

if command -v claude &>/dev/null; then
  info "Claude plugin validator"
  claude_validator_home="$(mktemp -d)"
  if (
    export HOME="$claude_validator_home"
    export LC_ALL=C
    export LANG=C
    export LC_CTYPE=C
    mkdir -p "$HOME/.claude"
    with_timeout 60 claude plugin validate "$DOTFILES_DIR" >/dev/null
  ); then
    rm -rf "$claude_validator_home"
  else
    validator_status=$?
    rm -rf "$claude_validator_home"
    exit "$validator_status"
  fi
fi

codex_validator="$HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py"
if [ -f "$codex_validator" ]; then
  info "Codex plugin validator"
  validator_output="$(mktemp)"
  if python3 "$codex_validator" "$DOTFILES_DIR/plugins/local-skills" >"$validator_output" 2>&1; then
    rm -f "$validator_output"
  elif grep -q "ModuleNotFoundError: No module named 'yaml'" "$validator_output"; then
    warn "Codex plugin validator dependency missing (PyYAML); skipped optional validator"
    rm -f "$validator_output"
  else
    cat "$validator_output" >&2
    rm -f "$validator_output"
    exit 1
  fi
fi

info "diff whitespace"
git diff --check

if [ "$mode" = "full" ]; then
  if command -v bats &>/dev/null; then
    info "Bats smoke tests"
    env LC_ALL=C LANG=C LC_CTYPE=C bats tests
  else
    warn "bats not found; skipped Bats smoke tests"
  fi
fi

info "OK ($mode)"
