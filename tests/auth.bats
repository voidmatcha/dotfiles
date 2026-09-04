#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  TEST_ROOT="$(mktemp -d)"
  TEST_HOME="$TEST_ROOT/home"
  TEST_BIN="$TEST_ROOT/bin"
  AUTH_TEST_LOG="$TEST_ROOT/security.log"
  mkdir -p "$TEST_HOME" "$TEST_BIN"
  : > "$AUTH_TEST_LOG"

  cat > "$TEST_BIN/security" <<'SH'
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" >> "$AUTH_TEST_LOG"

service=""
want_value=false
previous=""
for argument in "$@"; do
  if [ "$previous" = "-s" ]; then
    service="$argument"
  fi
  [ "$argument" = "-w" ] && want_value=true
  previous="$argument"
done

case "${1:-}" in
  find-generic-password)
    if $want_value; then
      case "$service" in
        io.voidmatcha.dotfiles.EXA_API_KEY) printf 'exa-secret\n' ;;
        io.voidmatcha.dotfiles.FIGMA_PERSONAL_API_KEY) printf 'figma-personal-secret\n' ;;
        io.voidmatcha.dotfiles.FIGMA_WORK_API_KEY) printf 'figma-work-secret\n' ;;
        io.voidmatcha.dotfiles.ZEPLIN_PERSONAL_ACCESS_TOKEN) printf 'zeplin-personal-secret\n' ;;
        io.voidmatcha.dotfiles.ZEPLIN_WORK_ACCESS_TOKEN) printf 'zeplin-work-secret\n' ;;
        io.voidmatcha.dotfiles.ATLASSIAN_PERSONAL_RO_AUTH) printf 'personal-secret\n' ;;
        io.voidmatcha.dotfiles.ATLASSIAN_WORK_RO_AUTH) printf 'work-ro-secret\n' ;;
        io.voidmatcha.dotfiles.ATLASSIAN_WORK_RW_AUTH) printf 'work-rw-secret\n' ;;
        io.voidmatcha.dotfiles.custom.*) printf 'custom-secret\n' ;;
        *) exit 44 ;;
      esac
    fi
    ;;
  add-generic-password|delete-generic-password) ;;
  *) exit 45 ;;
esac
SH
  chmod +x "$TEST_BIN/security"

  cat > "$TEST_BIN/auth-client" <<'SH'
#!/bin/bash
set -euo pipefail
for name in EXA_API_KEY FIGMA_API_KEY ZEPLIN_ACCESS_TOKEN LINEAR_API_KEY \
  ATLASSIAN_PERSONAL_RO_AUTH \
  ATLASSIAN_WORK_RO_AUTH ATLASSIAN_WORK_RW_AUTH; do
  [ -z "${!name:-}" ] || printf '%s=set\n' "$name"
done
SH
  chmod +x "$TEST_BIN/auth-client"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "dotfiles-auth stores a known secret through a Keychain-owned prompt" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" bash "$REPO_ROOT/scripts/auth.sh" set exa

  [ "$status" -eq 0 ]
  line="$(tail -n 1 "$AUTH_TEST_LOG")"
  [[ "$line" == add-generic-password* ]]
  [[ "$line" == *"-s io.voidmatcha.dotfiles.EXA_API_KEY"* ]]
  [[ "$line" == *"-w" ]]
  [ "${line##* }" = "-w" ]
  [[ "$output" != *"secret"* ]]
}

@test "dotfiles-auth status never retrieves or prints secret values" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" bash "$REPO_ROOT/scripts/auth.sh" status

  [ "$status" -eq 0 ]
  [[ "$output" == *"exa"* ]]
  [[ "$output" == *"stored"* ]]
  [[ "$output" != *"exa-secret"* ]]
  ! grep -q -- '-w' "$AUTH_TEST_LOG"
}

@test "installed dotfiles-auth symlink resolves the repository library" {
  ln -s "$REPO_ROOT/scripts/auth.sh" "$TEST_BIN/dotfiles-auth"

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" "$TEST_BIN/dotfiles-auth" status

  [ "$status" -eq 0 ]
  [[ "$output" == *"exa"* ]]
  [[ "$output" != *"No such file or directory"* ]]
}

@test "personal profile injects only personal and public-development secrets" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" bash "$REPO_ROOT/scripts/auth.sh" \
    run personal-ro -- "$TEST_BIN/auth-client"

  [ "$status" -eq 0 ]
  [[ "$output" == *"EXA_API_KEY=set"* ]]
  [[ "$output" == *"FIGMA_API_KEY=set"* ]]
  [[ "$output" == *"ZEPLIN_ACCESS_TOKEN=set"* ]]
  [[ "$output" == *"ATLASSIAN_PERSONAL_RO_AUTH=set"* ]]
  [[ "$output" != *"ATLASSIAN_WORK_RO_AUTH=set"* ]]
  [[ "$output" != *"ATLASSIAN_WORK_RW_AUTH=set"* ]]
  [[ "$output" != *"secret"* ]]
}

@test "work profile injects only work tool credentials" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" bash "$REPO_ROOT/scripts/auth.sh" \
    run work-ro -- "$TEST_BIN/auth-client"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ATLASSIAN_WORK_RO_AUTH=set"* ]]
  [[ "$output" == *"FIGMA_API_KEY=set"* ]]
  [[ "$output" == *"ZEPLIN_ACCESS_TOKEN=set"* ]]
  [[ "$output" != *"EXA_API_KEY=set"* ]]
  [[ "$output" != *"ATLASSIAN_PERSONAL_RO_AUTH=set"* ]]
  grep -q 'FIGMA_WORK_API_KEY' "$AUTH_TEST_LOG"
  grep -q 'ZEPLIN_WORK_ACCESS_TOKEN' "$AUTH_TEST_LOG"
  ! grep -q 'FIGMA_PERSONAL_API_KEY' "$AUTH_TEST_LOG"
  ! grep -q 'ZEPLIN_PERSONAL_ACCESS_TOKEN' "$AUTH_TEST_LOG"
}

@test "empty profile works under macOS Bash 3.2 nounset" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    EXA_API_KEY=inherited FIGMA_API_KEY=inherited \
    ZEPLIN_ACCESS_TOKEN=inherited ATLASSIAN_PERSONAL_RO_AUTH=inherited \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    run none -- "$TEST_BIN/auth-client"

  [ "$status" -eq 0 ]
  [ -z "$output" ]
  [[ "$output" != *"unbound variable"* ]]
}

@test "set all stores every non-write built-in credential" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    set all

  [ "$status" -eq 0 ]
  [ "$(grep -c '^add-generic-password ' "$AUTH_TEST_LOG")" -eq 7 ]
  grep -q 'FIGMA_PERSONAL_API_KEY' "$AUTH_TEST_LOG"
  grep -q 'FIGMA_WORK_API_KEY' "$AUTH_TEST_LOG"
  grep -q 'ZEPLIN_PERSONAL_ACCESS_TOKEN' "$AUTH_TEST_LOG"
  grep -q 'ZEPLIN_WORK_ACCESS_TOKEN' "$AUTH_TEST_LOG"
  grep -q 'ATLASSIAN_PERSONAL_RO_AUTH' "$AUTH_TEST_LOG"
  grep -q 'ATLASSIAN_WORK_RO_AUTH' "$AUTH_TEST_LOG"
  ! grep -q 'ATLASSIAN_WORK_RW_AUTH' "$AUTH_TEST_LOG"
  [[ "$output" == *"work-rw remains explicit"* ]]
}

@test "registered process credential follows its profile outside MCP clients" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    register linear LINEAR_API_KEY work-ro
  [ "$status" -eq 0 ]

  registry="$TEST_HOME/.config/dotfiles-auth/credentials.tsv"
  [ -f "$registry" ]
  grep -Fxq $'linear\tLINEAR_API_KEY\twork-ro' "$registry"

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    set linear
  [ "$status" -eq 0 ]
  grep -q 'io.voidmatcha.dotfiles.custom.linear' "$AUTH_TEST_LOG"

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    run work-ro -- "$TEST_BIN/auth-client"
  [ "$status" -eq 0 ]
  [[ "$output" == *"LINEAR_API_KEY=set"* ]]

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    run personal-ro -- "$TEST_BIN/auth-client"
  [ "$status" -eq 0 ]
  [[ "$output" != *"LINEAR_API_KEY=set"* ]]
}

@test "catalog exposes credential ownership and routing without secret reads" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    register sentry SENTRY_AUTH_TOKEN work-ro
  [ "$status" -eq 0 ]

  : > "$AUTH_TEST_LOG"
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    catalog

  [ "$status" -eq 0 ]
  [[ "$output" == *$'exa\tenv-token\tpersonal-ro\tEXA_API_KEY\tkeychain:io.voidmatcha.dotfiles.EXA_API_KEY'* ]]
  [[ "$output" == *$'sentry\tenv-token\twork-ro\tSENTRY_AUTH_TOKEN\tkeychain:io.voidmatcha.dotfiles.custom.sentry'* ]]
  [[ "$output" == *$'git-https\tnative\tunscoped\t-\tgit-credential-osxkeychain'* ]]
  [[ "$output" == *$'linkedin-session\tbrowser-session\tunscoped\t-\t'"$TEST_HOME"'/.linkedin-mcp/profile'* ]]
  [[ "$output" == *"custom-registry"*$TEST_HOME/.config/dotfiles-auth/credentials.tsv* ]]
  [ ! -s "$AUTH_TEST_LOG" ]
  [[ "$output" != *"custom-secret"* ]]
}

@test "status distinguishes browser-managed social sessions from Keychain tokens" {
  mkdir -p "$TEST_HOME/.linkedin-mcp/profile" "$TEST_HOME/.config/rdt-cli"
  touch "$TEST_HOME/.linkedin-mcp/profile/Preferences"
  touch "$TEST_HOME/.config/rdt-cli/credential.json"

  cat > "$TEST_BIN/twitter" <<'SH'
#!/bin/bash
exit 0
SH
  chmod +x "$TEST_BIN/twitter"

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" status

  [ "$status" -eq 0 ]
  [[ "$output" == *"linkedin-session"*"profile present"* ]]
  [[ "$output" == *"twitter-session"*"browser-managed"* ]]
  [[ "$output" == *"reddit-session"*"stored"* ]]
  ! grep -q -- '-w' "$AUTH_TEST_LOG"
}

@test "setup social owns supported login commands without exporting cookies" {
  social_log="$TEST_ROOT/social.log"
  : > "$social_log"

  cat > "$TEST_BIN/uvx" <<'SH'
#!/bin/bash
printf 'uvx %s\n' "$*" >> "$SOCIAL_TEST_LOG"
SH
  cat > "$TEST_BIN/twitter" <<'SH'
#!/bin/bash
printf 'twitter %s\n' "$*" >> "$SOCIAL_TEST_LOG"
[ "${1:-}" != "status" ] || exit 1
SH
  cat > "$TEST_BIN/rdt" <<'SH'
#!/bin/bash
printf 'rdt %s\n' "$*" >> "$SOCIAL_TEST_LOG"
if [ "${1:-}" = "status" ]; then exit 1; fi
SH
  cat > "$TEST_BIN/open" <<'SH'
#!/bin/bash
printf 'open %s\n' "$*" >> "$SOCIAL_TEST_LOG"
SH
  chmod +x "$TEST_BIN/uvx" "$TEST_BIN/twitter" "$TEST_BIN/rdt" \
    "$TEST_BIN/open"

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    SOCIAL_TEST_LOG="$social_log" AUTH_TEST_LOG="$AUTH_TEST_LOG" \
    /bin/bash "$REPO_ROOT/scripts/auth.sh" setup social

  [ "$status" -eq 0 ]
  grep -Fxq 'uvx mcp-server-linkedin@latest --login' "$social_log"
  grep -Fxq 'twitter status' "$social_log"
  grep -Fxq 'open https://x.com/login' "$social_log"
  grep -Fxq 'rdt status' "$social_log"
  grep -Fxq 'rdt login' "$social_log"
  [[ "$output" == *"Opened X/Twitter login"* ]]
  ! grep -q -- '-w' "$AUTH_TEST_LOG"
}

@test "setup all opens only allowlisted token pages and runs each login family" {
  browser_log="$TEST_ROOT/browser.log"
  : > "$browser_log"

  cat > "$TEST_BIN/gh" <<'SH'
#!/bin/bash
printf 'gh %s\n' "$*" >> "$BROWSER_TEST_LOG"
exit 0
SH
  cat > "$TEST_BIN/codex" <<'SH'
#!/bin/bash
printf 'codex %s\n' "$*" >> "$BROWSER_TEST_LOG"
exit 0
SH
  cat > "$TEST_BIN/uvx" <<'SH'
#!/bin/bash
printf 'uvx %s\n' "$*" >> "$BROWSER_TEST_LOG"
SH
  cat > "$TEST_BIN/twitter" <<'SH'
#!/bin/bash
printf 'twitter %s\n' "$*" >> "$BROWSER_TEST_LOG"
exit 0
SH
  cat > "$TEST_BIN/rdt" <<'SH'
#!/bin/bash
printf 'rdt %s\n' "$*" >> "$BROWSER_TEST_LOG"
exit 0
SH
  cat > "$TEST_BIN/open" <<'SH'
#!/bin/bash
printf 'open %s\n' "$*" >> "$BROWSER_TEST_LOG"
SH
  chmod +x "$TEST_BIN/gh" "$TEST_BIN/codex" "$TEST_BIN/uvx" \
    "$TEST_BIN/twitter" "$TEST_BIN/rdt" "$TEST_BIN/open"

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    BROWSER_TEST_LOG="$browser_log" AUTH_TEST_LOG="$AUTH_TEST_LOG" \
    /bin/bash "$REPO_ROOT/scripts/auth.sh" setup all

  [ "$status" -eq 0 ]
  grep -Fxq 'gh auth status' "$browser_log"
  grep -Fxq 'codex login status' "$browser_log"
  grep -Fxq 'codex mcp login figma' "$browser_log"
  grep -Fxq 'codex mcp login atlassian-personal-ro' "$browser_log"
  grep -Fxq 'codex mcp login atlassian-work-ro' "$browser_log"
  grep -Fxq 'uvx mcp-server-linkedin@latest --login' "$browser_log"
  grep -Fxq 'twitter status' "$browser_log"
  grep -Fxq 'rdt status' "$browser_log"
  grep -Fxq 'open https://www.figma.com/settings' "$browser_log"
  grep -Fxq 'open https://app.zeplin.io/profile/developer' "$browser_log"
  grep -Fxq \
    'open https://id.atlassian.com/manage-profile/security/api-tokens' \
    "$browser_log"
  [ "$(grep -c '^open ' "$browser_log")" -eq 3 ]
  [[ "$output" == *"Confirm the active browser account"* ]]
  ! grep -q -- '-w' "$AUTH_TEST_LOG"
}

@test "setup work continues when a token page cannot be opened" {
  browser_log="$TEST_ROOT/browser-failure.log"
  : > "$browser_log"

  cat > "$TEST_BIN/codex" <<'SH'
#!/bin/bash
exit 0
SH
  cat > "$TEST_BIN/open" <<'SH'
#!/bin/bash
printf 'open %s\n' "$*" >> "$BROWSER_TEST_LOG"
exit 7
SH
  chmod +x "$TEST_BIN/codex" "$TEST_BIN/open"

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    BROWSER_TEST_LOG="$browser_log" AUTH_TEST_LOG="$AUTH_TEST_LOG" \
    /bin/bash "$REPO_ROOT/scripts/auth.sh" setup work

  [ "$status" -eq 0 ]
  [ "$(grep -c '^open ' "$browser_log")" -eq 3 ]
  [[ "$output" == *"Could not open Figma token settings"* ]]
  [[ "$output" == *"Store work collaboration tokens"* ]]
}

@test "setup social degrades safely when optional clients are absent" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    AUTH_TEST_LOG="$AUTH_TEST_LOG" /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    setup social

  [ "$status" -eq 0 ]
  [[ "$output" == *"uvx is not installed"* ]]
  [[ "$output" == *"twitter is not installed"* ]]
  [[ "$output" == *"rdt is not installed"* ]]
}

@test "custom credential registration rejects unsafe metadata" {
  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    register all LINEAR_API_KEY work-ro
  [ "$status" -eq 2 ]

  run env HOME="$TEST_HOME" PATH="$TEST_BIN:/usr/bin:/bin" \
    /bin/bash "$REPO_ROOT/scripts/auth.sh" \
    register linear 'BAD=$(touch /tmp/nope)' work-ro
  [ "$status" -eq 2 ]
  [ ! -e "$TEST_HOME/.config/dotfiles-auth/credentials.tsv" ]
}

@test "auto profile follows repo-local git config but persistent rw is rejected" {
  repo="$TEST_ROOT/repo"
  mkdir -p "$repo"
  git -C "$repo" init -q
  git -C "$repo" config dotfiles.authProfile work-ro

  run bash -c 'cd "$1" && env HOME="$2" PATH="$3:/usr/bin:/bin" AUTH_TEST_LOG="$4" \
    bash "$5/scripts/auth.sh" run auto -- "$3/auth-client"' \
    _ "$repo" "$TEST_HOME" "$TEST_BIN" "$AUTH_TEST_LOG" "$REPO_ROOT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ATLASSIAN_WORK_RO_AUTH=set"* ]]

  run bash -c 'cd "$1" && env HOME="$2" PATH="$3:/usr/bin:/bin" \
    bash "$4/scripts/auth.sh" profile set work-rw' \
    _ "$repo" "$TEST_HOME" "$TEST_BIN" "$REPO_ROOT"
  [ "$status" -eq 2 ]
  [[ "$output" == *"work-rw is command-scoped"* ]]
  [ "$(git -C "$repo" config dotfiles.authProfile)" = "work-ro" ]
}

@test "skills cleanup retires workflow skills from every active skill root" {
  codex_home="$TEST_HOME/.codex"
  agents_skills="$TEST_HOME/.agents/skills"
  claude_skills="$TEST_HOME/.claude/skills"
  retired_skills=(
    autopilot
    ralplan
    ultraqa
    ultrawork
    asset-improver
    cmux-doctor
    cmux-handoff-runner
    purplemux-bridge
  )
  mkdir -p "$codex_home/skills/keep-me" "$agents_skills" "$claude_skills"
  touch "$codex_home/skills/keep-me/SKILL.md"
  cat > "$TEST_HOME/.agents/.skill-lock.json" <<'JSON'
{
  "version": 3,
  "skills": {
    "ultrawork": {"source": "yeachan-heo/oh-my-claudecode"},
    "keep-me": {"source": "user/example"}
  }
}
JSON
  for name in "${retired_skills[@]}"; do
    mkdir -p "$codex_home/skills/$name"
    mkdir -p "$agents_skills/$name"
    ln -s "../../.agents/skills/$name" "$claude_skills/$name"
  done

  run env HOME="$TEST_HOME" CODEX_HOME="$codex_home" DOTFILES_DIR="$REPO_ROOT" \
    PATH="/usr/bin:/bin" bash "$REPO_ROOT/scripts/skills.sh" codex --retire-only

  [ "$status" -eq 0 ]
  [ -d "$codex_home/skills/keep-me" ]
  for name in "${retired_skills[@]}"; do
    [ ! -e "$codex_home/skills/$name" ]
    [ ! -e "$agents_skills/$name" ]
    [ ! -L "$claude_skills/$name" ]
    [ -d "$TEST_HOME/.Trash/dotfiles-retired-workflow-skills/codex/$name" ]
    [ -d "$TEST_HOME/.Trash/dotfiles-retired-workflow-skills/agents/$name" ]
    [ -L "$TEST_HOME/.Trash/dotfiles-retired-workflow-skills/claude/$name" ]
  done
  [ "$(python3 -c 'import json,sys; print("ultrawork" in json.load(open(sys.argv[1]))["skills"])' "$TEST_HOME/.agents/.skill-lock.json")" = "False" ]
  [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["skills"]["keep-me"]["source"])' "$TEST_HOME/.agents/.skill-lock.json")" = "user/example" ]
}

@test "skills cleanup uninstalls graphify only when pip owns it" {
  graphify_log="$TEST_ROOT/graphify.log"
  graphify_bin="$TEST_BIN/graphify"
  : > "$graphify_log"
  touch "$graphify_bin"
  chmod +x "$graphify_bin"

  cat > "$TEST_BIN/python3" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$GRAPHIFY_TEST_LOG"
if [ "$*" = "-m pip show graphifyy" ]; then
  exit 0
fi
if [ "$*" = "-m pip uninstall -y graphifyy" ]; then
  rm -f "$GRAPHIFY_TEST_BIN"
  exit 0
fi
exit 2
SH
  chmod +x "$TEST_BIN/python3"

  run env HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" \
    DOTFILES_DIR="$REPO_ROOT" PATH="$TEST_BIN:/usr/bin:/bin" \
    GRAPHIFY_TEST_LOG="$graphify_log" GRAPHIFY_TEST_BIN="$graphify_bin" \
    bash "$REPO_ROOT/scripts/skills.sh" codex --retire-only

  [ "$status" -eq 0 ]
  [ ! -e "$graphify_bin" ]
  grep -Fxq -- '-m pip show graphifyy' "$graphify_log"
  grep -Fxq -- '-m pip uninstall -y graphifyy' "$graphify_log"
}

@test "skills cleanup preserves an unmanaged graphify executable" {
  graphify_bin="$TEST_BIN/graphify"
  touch "$graphify_bin"
  chmod +x "$graphify_bin"

  cat > "$TEST_BIN/python3" <<'SH'
#!/bin/bash
[ "$*" != "-m pip show graphifyy" ] || exit 1
exit 2
SH
  chmod +x "$TEST_BIN/python3"

  run env HOME="$TEST_HOME" CODEX_HOME="$TEST_HOME/.codex" \
    DOTFILES_DIR="$REPO_ROOT" PATH="$TEST_BIN:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/skills.sh" codex --retire-only

  [ "$status" -eq 0 ]
  [ -e "$graphify_bin" ]
  [[ "$output" == *"not owned by the graphifyy package"* ]]
}
