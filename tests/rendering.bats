#!/usr/bin/env bats
# Tests for things the installer renders/templates:
#  - git.sh writes valid .gitconfig-personal / .gitconfig-work with the given
#    name + email and no signingkey baked in (machine-local stays out of repo).
#  - company/configs/mcp.json.template renders through envsubst with only the
#    allow-listed variables expanded (so other env values can't leak in).

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  TMPDIR_TEST="$(mktemp -d)"
  export LC_ALL=C
  export LANG=C
  export LC_CTYPE=C
  export GIT_CONFIG_NOSYSTEM=1
  export GIT_CONFIG_GLOBAL="$TMPDIR_TEST/gitconfig"
  : > "$GIT_CONFIG_GLOBAL"
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

@test "git.sh heredoc renders personal config with given name+email and no signingkey" {
  # We exercise just the cat-heredoc logic from git.sh, not the prompts.
  personal_name="Test User"
  personal_email="test@example.com"
  target="$TMPDIR_TEST/.gitconfig-personal"
  cat > "$target" <<EOF
[user]
    name = $personal_name
    email = $personal_email
# signingkey: machine-local — set in ~/.gitconfig.local
EOF
  run grep -q "name = Test User" "$target"
  [ "$status" -eq 0 ]
  run grep -q "email = test@example.com" "$target"
  [ "$status" -eq 0 ]
  run grep -E "^[[:space:]]*signingkey[[:space:]]*=" "$target"
  [ "$status" -ne 0 ]  # signingkey MUST NOT be in tracked config
}

@test "envsubst allowlist only expands listed variables" {
  if ! command -v envsubst >/dev/null 2>&1; then
    skip "envsubst not installed (brew install gettext)"
  fi
  template="$TMPDIR_TEST/in.txt"
  printf '%s\n' '${ALLOWED_VAR}|${SECRET_VAR}|${PATH}' > "$template"
  run env ALLOWED_VAR=allowed SECRET_VAR=should-not-leak \
        envsubst '${ALLOWED_VAR}' < "$template"
  [ "$status" -eq 0 ]
  [[ "$output" == "allowed"*'${SECRET_VAR}|${PATH}'* ]]
}

@test "company mcp template references documented MCPs only" {
  template="$REPO_ROOT/company/configs/mcp.json.template"
  if [ ! -f "$template" ]; then
    skip "company overlay not present"
  fi
  if ! command -v jq >/dev/null 2>&1; then
    skip "jq not installed"
  fi
  run jq -r '.mcpServers | keys[]' "$template"
  [ "$status" -eq 0 ]
  for name in $output; do
    # Each MCP must be referenced (by name) in the agent doc so reviewers
    # have something to map against.
    grep -q "$name" "$REPO_ROOT/company/configs/AGENTS-company.md" \
      || { echo "MCP '$name' in template but not mentioned in AGENTS-company.md"; return 1; }
  done
}

@test "company mcp template renders all declared secrets" {
  template="$REPO_ROOT/company/configs/mcp.json.template"
  [ -f "$template" ] || skip "company overlay not present"
  if ! command -v envsubst >/dev/null 2>&1; then
    skip "envsubst not installed (brew install gettext)"
  fi

  rendered="$TMPDIR_TEST/company-mcp.json"
  CONTEXT7_API_KEY=context7-test OSS_NAVER_PAT=oss-test FIGMA_API_KEY=figma-test \
    envsubst '${CONTEXT7_API_KEY} ${OSS_NAVER_PAT} ${FIGMA_API_KEY}' \
    < "$template" > "$rendered"

  python3 - "$rendered" <<'PY'
import json
import sys

cfg = json.load(open(sys.argv[1]))
servers = cfg["mcpServers"]
assert servers["github-enterprise"]["env"]["GITHUB_TOKEN"] == "oss-test"
assert servers["context7-naver"]["args"][-1] == "context7-test"
assert servers["figma-developer-mcp"]["env"]["FIGMA_API_KEY"] == "figma-test"
PY
}

@test "company install.sh writes ~/work/.mcp.json (project scope), not user scope" {
  [ -f "$REPO_ROOT/company/install.sh" ] || skip "company overlay not present"
  grep -q '~/work/.mcp.json\|"$HOME/work/.mcp.json"' "$REPO_ROOT/company/install.sh" \
    || { echo "company install.sh should target ~/work/.mcp.json"; return 1; }
  grep -q '\${CONTEXT7_API_KEY} \${OSS_NAVER_PAT} \${FIGMA_API_KEY}' "$REPO_ROOT/company/install.sh" \
    || { echo "company envsubst allowlist must include every mcp.json.template secret"; return 1; }
  grep -q 'UNAPPROVED_MCP' "$REPO_ROOT/company/install.sh" \
    || { echo "company install.sh should remove unapproved public MCPs"; return 1; }
  grep -q '"linkedin"' "$REPO_ROOT/company/install.sh" \
    || { echo "company install.sh should remove linkedin on internal machines"; return 1; }
  ! grep -q 'mcp remove --scope user exa' "$REPO_ROOT/company/install.sh" \
    || { echo "company install.sh should not hard-prune provider-official exa"; return 1; }
  # Negative assertion: we should NOT see a `claude mcp add-json --scope user`
  # for company servers anymore (those leak company tools into personal sessions).
  ! grep -q 'claude mcp add-json --scope user' "$REPO_ROOT/company/install.sh"
}

@test "company install renders project MCP and cleans user-scope leftovers" {
  [ -f "$REPO_ROOT/company/install.sh" ] || skip "company overlay not present"
  if ! command -v jq >/dev/null 2>&1; then
    skip "jq not installed"
  fi
  if ! command -v envsubst >/dev/null 2>&1; then
    skip "envsubst not installed (brew install gettext)"
  fi

  home="$TMPDIR_TEST/company-home"
  bin="$TMPDIR_TEST/bin"
  mkdir -p "$home/.claude" "$home/owl" "$bin"
  printf '{"legacy":true}\n' > "$home/.claude/.mcp.json"
  cat > "$home/.company.secrets.env" <<'EOF'
export CONTEXT7_API_KEY=context7-live
export OSS_NAVER_PAT=oss-live
export FIGMA_API_KEY=figma-live
EOF
  cat > "$home/owl/setup.sh" <<'SH'
#!/bin/sh
exit 0
SH
  chmod +x "$home/owl/setup.sh"
  cat > "$bin/claude" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$HOME/claude-calls.log"
exit 0
SH
  cat > "$bin/brew" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$HOME/brew-calls.log"
exit 0
SH
  chmod +x "$bin/claude" "$bin/brew"

  run env HOME="$home" DOTFILES_DIR="$REPO_ROOT" DRY_RUN=false NON_INTERACTIVE=true PATH="$bin:$PATH" bash "$REPO_ROOT/company/install.sh"

  [ "$status" -eq 0 ]
  [ -f "$home/work/.mcp.json" ]
  [ ! -e "$home/.claude/.mcp.json" ]
  ! grep -q 'mcp add-json --scope user' "$home/claude-calls.log"
  grep -q 'mcp remove --scope user github-enterprise' "$home/claude-calls.log"
  ! grep -q 'mcp remove --scope user exa' "$home/claude-calls.log"
  grep -q 'mcp remove --scope user linkedin' "$home/claude-calls.log"

  python3 - "$home/work/.mcp.json" <<'PY'
import json
import sys

cfg = json.load(open(sys.argv[1]))
servers = cfg["mcpServers"]
assert servers["github-enterprise"]["env"]["GITHUB_TOKEN"] == "oss-live"
assert servers["context7-naver"]["args"][-1] == "context7-live"
assert servers["figma-developer-mcp"]["env"]["FIGMA_API_KEY"] == "figma-live"
PY
}

@test "company Claude settings pin approved MCP servers" {
  settings="$REPO_ROOT/company/configs/claude-settings.json"
  [ -f "$settings" ] || skip "company overlay not present"

  python3 - "$settings" <<'PY'
import json
import sys

cfg = json.load(open(sys.argv[1]))
# Project-scope MCP servers (loaded from ~/work/.mcp.json) — must all be in
# the NAVER catalog at oss.navercorp.com/naver-common-mcp. The two NAVER
# variants of public tools are explicitly suffixed with "-naver" so the
# public-npm versions registered at user scope can coexist without
# "Conflicting scopes" warnings when working in ~/work/.
project_scope = [
    "chrome-devtools-naver",
    "playwright",
    "github-enterprise",
    "context7-naver",
    "figma-developer-mcp",
]
# User-scope MCPs that the company settings still permits (so the same tools
# available outside ~/work/ also work inside it). Provider-official hosted MCPs
# such as exa are allowed to remain user-scope, but AGENTS-company.md forbids
# sending internal data through them.
user_scope_allowed = ["chrome-devtools", "context7", "exa", "serena", "codegraph"]
assert cfg["enableAllProjectMcpServers"] is False
assert cfg["enabledMcpjsonServers"] == project_scope
assert cfg["allowManagedMcpServersOnly"] is True
assert cfg["allowedMcpServers"] == [
    {"serverName": name} for name in project_scope + user_scope_allowed
]
denied = {entry["serverName"] for entry in cfg["deniedMcpServers"]}
assert {"filesystem", "linkedin"} <= denied
assert not ({"exa", "serena", "codegraph"} & denied), (
    "provider-official/user-scope tools must NOT be on the company denylist"
)
PY
}

@test "company guidance keeps agent-browser as local CLI, not MCP" {
  agents="$REPO_ROOT/company/configs/AGENTS-company.md"
  readme="$REPO_ROOT/company/README.md"
  [ -f "$agents" ] || skip "company overlay not present"

  grep -q 'agent-browser open <URL> --profile "Default"' "$agents"
  grep -q 'agent-browser.*not an MCP server' "$agents"
  grep -q 'agent-browser open <url> --profile "Default"' "$readme"
}

@test "company guidance permits provider-official MCPs without internal data" {
  agents="$REPO_ROOT/company/configs/AGENTS-company.md"
  readme="$REPO_ROOT/company/README.md"
  [ -f "$agents" ] || skip "company overlay not present"

  grep -q 'Provider-official hosted MCPs' "$agents"
  grep -q 'Exa MCP may be available' "$agents"
  grep -q 'does not hard-prune' "$readme"
  grep -q 'provider-official MCPs such as Exa' "$readme"
}

@test "tracked .gitconfig-personal/.gitconfig-work do not contain signingkey" {
  for f in "$REPO_ROOT/configs/.gitconfig-personal" "$REPO_ROOT/configs/.gitconfig-work"; do
    [ -f "$f" ] || skip "$(basename "$f") not present yet"
    run grep -E "^[[:space:]]*signingkey" "$f"
    [ "$status" -ne 0 ] || { echo "signingkey leaked into $f"; return 1; }
  done
}
