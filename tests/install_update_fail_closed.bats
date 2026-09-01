#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  TMPDIR_TEST="$(mktemp -d)"
  export LC_ALL=C
  export LANG=C
  export LC_CTYPE=C
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

make_executable() {
  chmod +x "$1"
}

@test "bootstrap aborts a stale existing checkout when fast-forward pull fails" {
  root="$TMPDIR_TEST/bootstrap-root"
  fakebin="$TMPDIR_TEST/bootstrap-bin"
  log="$TMPDIR_TEST/bootstrap.log"
  mkdir -p "$root/.git" "$fakebin"
  cat > "$fakebin/uname" <<'SH'
#!/bin/bash
printf '%s\n' Darwin
SH
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf 'git %s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"pull --ff-only"*) exit 7 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  chmod +x "$fakebin/uname" "$fakebin/git" "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/bootstrap.sh" --dry-run

  [ "$status" -ne 0 ]
  [[ "$output" == *"fast-forward pull failed"* ]]
  run grep -Fq install-ran "$log"
  [ "$status" -eq 1 ]
}

@test "bootstrap propagates a company-overlay skip after submodule refresh failure" {
  root="$TMPDIR_TEST/bootstrap-submodule-root"
  fakebin="$TMPDIR_TEST/bootstrap-submodule-bin"
  log="$TMPDIR_TEST/bootstrap-submodule.log"
  mkdir -p "$root/.git" "$fakebin"
  cat > "$fakebin/uname" <<'SH'
#!/bin/bash
printf '%s\n' Darwin
SH
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf 'git %s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"pull --ff-only"*) exit 0 ;;
  *"submodule update --init --recursive"*) exit 7 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf 'install skip_company=%s %s\n' "${SKIP_COMPANY_OVERLAY:-unset}" "$*" >> "$CALL_LOG"
SH
  chmod +x "$fakebin/uname" "$fakebin/git" "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/bootstrap.sh" --dry-run

  [ "$status" -eq 0 ]
  [[ "$output" == *"company overlay will be skipped"* ]]
  grep -Fq 'install skip_company=true --dry-run' "$log"
}

@test "bootstrap refuses a dirty existing checkout before pull or install" {
  root="$TMPDIR_TEST/bootstrap-dirty-root"
  fakebin="$TMPDIR_TEST/bootstrap-dirty-bin"
  log="$TMPDIR_TEST/bootstrap-dirty.log"
  mkdir -p "$root/.git" "$fakebin"
  cat > "$fakebin/uname" <<'SH'
#!/bin/bash
printf '%s\n' Darwin
SH
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf 'git %s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"status --porcelain"*) printf '%s\n' ' M local-change'; exit 0 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  chmod +x "$fakebin/uname" "$fakebin/git" "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/bootstrap.sh" --dry-run

  [ "$status" -ne 0 ]
  [[ "$output" == *"uncommitted changes"*"refusing to pull or install"* ]]
  run grep -F 'pull --ff-only' "$log"
  [ "$status" -ne 0 ]
  run grep -F install-ran "$log"
  [ "$status" -ne 0 ]
}

@test "bootstrap fails closed when existing checkout status cannot be read" {
  root="$TMPDIR_TEST/bootstrap-status-fail-root"
  fakebin="$TMPDIR_TEST/bootstrap-status-fail-bin"
  log="$TMPDIR_TEST/bootstrap-status-fail.log"
  mkdir -p "$root/.git" "$fakebin"
  cat > "$fakebin/uname" <<'SH'
#!/bin/bash
printf '%s\n' Darwin
SH
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf 'git %s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"status --porcelain"*) exit 7 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  chmod +x "$fakebin/uname" "$fakebin/git" "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/bootstrap.sh" --dry-run

  [ "$status" -ne 0 ]
  [[ "$output" == *"failed to inspect existing checkout status"*"refusing to pull or install"* ]]
  run grep -F 'pull --ff-only' "$log"
  [ "$status" -ne 0 ]
  run grep -F install-ran "$log"
  [ "$status" -ne 0 ]
}

@test "bootstrap rejects an existing path owned by a parent git repository" {
  root="$TMPDIR_TEST/bootstrap-wrong-root/child"
  wrong_root="$TMPDIR_TEST/bootstrap-wrong-root"
  fakebin="$TMPDIR_TEST/bootstrap-wrong-root-bin"
  log="$TMPDIR_TEST/bootstrap-wrong-root.log"
  mkdir -p "$root/.git" "$fakebin"
  cat > "$fakebin/uname" <<'SH'
#!/bin/bash
printf '%s\n' Darwin
SH
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf 'git %s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) printf '%s\n' "$WRONG_REPO_ROOT"; exit 0 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  chmod +x "$fakebin/uname" "$fakebin/git" "$root/install.sh"

  run env DOTFILES_DIR="$root" WRONG_REPO_ROOT="$wrong_root" \
    PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/bootstrap.sh" --dry-run

  [ "$status" -ne 0 ]
  [[ "$output" == *"existing checkout root mismatch"*"refusing to pull or install"* ]]
  run grep -F 'status --porcelain' "$log"
  [ "$status" -ne 0 ]
  run grep -F 'pull --ff-only' "$log"
  [ "$status" -ne 0 ]
  run grep -F install-ran "$log"
  [ "$status" -ne 0 ]
}

@test "update stops dependent submodule and install steps after pull failure" {
  root="$TMPDIR_TEST/update-root"
  fakebin="$TMPDIR_TEST/update-bin"
  log="$TMPDIR_TEST/update.log"
  mkdir -p "$root" "$fakebin"

  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"status --porcelain"*) exit 0 ;;
  *"pull --ff-only"*) exit "${PULL_STATUS:-0}" ;;
  *"submodule update --init --recursive"*) exit "${SUBMODULE_STATUS:-0}" ;;
esac
exit 0
SH
  make_executable "$fakebin/git"

  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf 'install skip_company=%s %s\n' "${SKIP_COMPANY_OVERLAY:-unset}" "$*" >> "$CALL_LOG"
exit "${INSTALL_STATUS:-0}"
SH
  make_executable "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    PULL_STATUS=7 SUBMODULE_STATUS=8 INSTALL_STATUS=9 \
    bash "$REPO_ROOT/scripts/update.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"git pull"*"failed"* ]]
  [[ "$output" == *"skipping submodule refresh"* ]]
  [[ "$output" == *"skipping install.sh"*"checkout refresh did not complete safely"* ]]
  [[ "$output" == *"completed with 1 failure"* ]]

  grep -q 'pull --ff-only' "$log"
  run grep -q 'submodule update --init --recursive' "$log"
  [ "$status" -eq 1 ]
  run grep -q '^install ' "$log"
  [ "$status" -eq 1 ]
}

@test "update setup-only applies current config without version upgrades" {
  root="$TMPDIR_TEST/update-setup-root"
  fakebin="$TMPDIR_TEST/update-setup-bin"
  log="$TMPDIR_TEST/update-setup.log"
  mkdir -p "$root" "$fakebin"

  cat > "$fakebin/git" <<'SH'
#!/bin/bash
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' "$*" > "$CALL_LOG"
SH
  make_executable "$fakebin/git"
  make_executable "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/update.sh" --no-pull --setup-only

  [ "$status" -eq 0 ]
  [ "$(cat "$log")" = "--non-interactive" ]
  [[ "$output" == *"setup only"* ]]
  [[ "$output" != *"version upgrades"* ]]
}

@test "update fails closed and skips install when checkout is not a git repository" {
  root="$TMPDIR_TEST/update-not-repo-root"
  fakebin="$TMPDIR_TEST/update-not-repo-bin"
  log="$TMPDIR_TEST/update-not-repo.log"
  mkdir -p "$root" "$fakebin"
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
exit 1
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  make_executable "$fakebin/git"
  make_executable "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/update.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"git checkout validation failed"* ]]
  [[ "$output" == *"skipping install.sh"* ]]
  [ ! -e "$log" ]
}

@test "update fails closed when checkout status cannot be read" {
  root="$TMPDIR_TEST/update-status-fail-root"
  fakebin="$TMPDIR_TEST/update-status-fail-bin"
  log="$TMPDIR_TEST/update-status-fail.log"
  mkdir -p "$root" "$fakebin"
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"status --porcelain"*) exit 7 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  make_executable "$fakebin/git"
  make_executable "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/update.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"git checkout status failed"* ]]
  [[ "$output" == *"skipping install.sh"* ]]
  run grep -F 'pull --ff-only' "$log"
  [ "$status" -ne 0 ]
  run grep -F 'submodule update --init --recursive' "$log"
  [ "$status" -ne 0 ]
  run grep -F install-ran "$log"
  [ "$status" -ne 0 ]
}

@test "update rejects a path owned by a parent git repository even with no-pull" {
  root="$TMPDIR_TEST/update-wrong-root/child"
  wrong_root="$TMPDIR_TEST/update-wrong-root"
  fakebin="$TMPDIR_TEST/update-wrong-root-bin"
  log="$TMPDIR_TEST/update-wrong-root.log"
  mkdir -p "$root" "$fakebin"
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) printf '%s\n' "$WRONG_REPO_ROOT"; exit 0 ;;
esac
exit 0
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  make_executable "$fakebin/git"
  make_executable "$root/install.sh"

  run env DOTFILES_DIR="$root" WRONG_REPO_ROOT="$wrong_root" \
    PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/update.sh" --no-pull

  [ "$status" -ne 0 ]
  [[ "$output" == *"dotfiles checkout root mismatch"* ]]
  [[ "$output" == *"git checkout validation failed"* ]]
  [[ "$output" == *"skipping install.sh"* ]]
  run grep -F 'status --porcelain' "$log"
  [ "$status" -ne 0 ]
  run grep -F 'pull --ff-only' "$log"
  [ "$status" -ne 0 ]
  run grep -F install-ran "$log"
  [ "$status" -ne 0 ]
}

@test "update fails closed and skips install for a dirty checkout" {
  root="$TMPDIR_TEST/update-dirty-root"
  fakebin="$TMPDIR_TEST/update-dirty-bin"
  log="$TMPDIR_TEST/update-dirty.log"
  mkdir -p "$root" "$fakebin"
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"status --porcelain"*) printf '%s\n' ' M local-change'; exit 0 ;;
  *) printf 'unexpected git call: %s\n' "$*" >> "$CALL_LOG"; exit 0 ;;
esac
SH
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf '%s\n' install-ran >> "$CALL_LOG"
SH
  make_executable "$fakebin/git"
  make_executable "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/update.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"git pull (dirty checkout) failed"* ]]
  [[ "$output" == *"skipping install.sh"* ]]
  [ ! -e "$log" ]
}

@test "update skips only the company overlay after submodule refresh failure" {
  root="$TMPDIR_TEST/update-submodule-root"
  fakebin="$TMPDIR_TEST/update-submodule-bin"
  log="$TMPDIR_TEST/update-submodule.log"
  mkdir -p "$root" "$fakebin"

  cat > "$fakebin/git" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"rev-parse --show-toplevel"*) cd "$DOTFILES_DIR" && pwd -P; exit 0 ;;
  *"status --porcelain"*) exit 0 ;;
  *"pull --ff-only"*) exit 0 ;;
  *"submodule update --init --recursive"*) exit 8 ;;
esac
exit 0
SH
  make_executable "$fakebin/git"
  cat > "$root/install.sh" <<'SH'
#!/bin/bash
printf 'install skip_company=%s %s\n' "${SKIP_COMPANY_OVERLAY:-unset}" "$*" >> "$CALL_LOG"
exit 0
SH
  make_executable "$root/install.sh"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/update.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"git submodule update"*"failed"* ]]
  [[ "$output" == *"completed with 1 failure"* ]]
  grep -Fq 'install skip_company=true --non-interactive --upgrade' "$log"
}

@test "local Claude plugin refreshes existing marketplace and plugin then verifies cache inventory" {
  root="$TMPDIR_TEST/skills-root"
  home="$TMPDIR_TEST/skills-home"
  fakebin="$TMPDIR_TEST/skills-bin"
  log="$TMPDIR_TEST/skills.log"
  mkdir -p "$root/.claude-plugin" \
    "$root/plugins/local-skills/.claude-plugin" \
    "$root/plugins/local-skills/.codex-plugin" \
    "$root/plugins/local-skills/skills/demo-skill" \
    "$home/.claude/plugins" "$fakebin"
  cp "$REPO_ROOT/.claude-plugin/marketplace.json" "$root/.claude-plugin/marketplace.json"
  cp "$REPO_ROOT/plugins/local-skills/.claude-plugin/plugin.json" "$root/plugins/local-skills/.claude-plugin/plugin.json"
  cp "$REPO_ROOT/plugins/local-skills/.codex-plugin/plugin.json" "$root/plugins/local-skills/.codex-plugin/plugin.json"
  mkdir -p "$root/plugins/local-skills/skills/example-skill"
  printf '%s\n' 'name: example-skill' > "$root/plugins/local-skills/skills/example-skill/SKILL.md"
  printf '%s\n' 'name: demo-skill' > "$root/plugins/local-skills/skills/demo-skill/SKILL.md"
  cat > "$home/.claude/plugins/known_marketplaces.json" <<'JSON'
{"dotfiles-local":{"source":{"source":"directory","path":"/tmp/dotfiles"}}}
JSON
  cat > "$home/.claude/plugins/installed_plugins.json" <<'JSON'
{"version":2,"plugins":{"local-skills@dotfiles-local":[{"scope":"user","installPath":"/stale/cache","version":"0.0.0"}]}}
JSON

  cat > "$fakebin/curl" <<'SH'
#!/bin/bash
dest="${@: -1}"
printf '%s\n' 'name: grill-me' > "$dest"
SH
  make_executable "$fakebin/curl"

  cat > "$fakebin/claude" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$CALL_LOG"
if [ "$1 $2 $3" = "plugin marketplace update" ]; then
  exit 0
fi
if [ "$1 $2" = "plugin update" ]; then
  if [ "${STUB_PLUGIN_DRIFT:-0}" = "1" ]; then
    exit 0
  fi
  version=$(jq -r '.version' "$DOTFILES_DIR/plugins/local-skills/.claude-plugin/plugin.json")
  cache="$HOME/.claude/plugins/cache/dotfiles-local/local-skills/$version"
  mkdir -p "$cache/.claude-plugin"
  cp "$DOTFILES_DIR/plugins/local-skills/.claude-plugin/plugin.json" "$cache/.claude-plugin/plugin.json"
  cp -R "$DOTFILES_DIR/plugins/local-skills/skills" "$cache/skills"
  mkdir -p "$DOTFILES_DIR/plugins/local-skills/skills/example-skill/__pycache__"
  printf '%s\n' runtime-only > "$DOTFILES_DIR/plugins/local-skills/skills/example-skill/__pycache__/ignored.pyc"
  jq -n --arg path "$cache" --arg version "$version" \
    '{version:2,plugins:{"local-skills@dotfiles-local":[{scope:"user",installPath:$path,version:$version}]}}' \
    > "$HOME/.claude/plugins/installed_plugins.json"
  exit 0
fi
exit 0
SH
  make_executable "$fakebin/claude"

  run env HOME="$home" DOTFILES_DIR="$root" PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/skills.sh" claude

  [ "$status" -eq 0 ]
  grep -Fxq 'plugin marketplace update dotfiles-local' "$log"
  grep -Fxq 'plugin update local-skills@dotfiles-local' "$log"
  [[ "$output" == *"Verified local Claude plugin content/cache"* ]]
}

@test "local Claude plugin update fails closed when cached skill content stays stale" {
  root="$TMPDIR_TEST/skills-drift-root"
  home="$TMPDIR_TEST/skills-drift-home"
  fakebin="$TMPDIR_TEST/skills-drift-bin"
  mkdir -p "$root/.claude-plugin" \
    "$root/plugins/local-skills/.claude-plugin" \
    "$root/plugins/local-skills/.codex-plugin" \
    "$root/plugins/local-skills/skills/shared-skill" \
    "$home/.claude/plugins" "$fakebin"
  cp "$REPO_ROOT/.claude-plugin/marketplace.json" "$root/.claude-plugin/marketplace.json"
  cp "$REPO_ROOT/plugins/local-skills/.claude-plugin/plugin.json" "$root/plugins/local-skills/.claude-plugin/plugin.json"
  cp "$REPO_ROOT/plugins/local-skills/.codex-plugin/plugin.json" "$root/plugins/local-skills/.codex-plugin/plugin.json"
  printf '%s\n' 'name: shared-skill' 'content: current' > "$root/plugins/local-skills/skills/shared-skill/SKILL.md"
  cat > "$home/.claude/plugins/known_marketplaces.json" <<'JSON'
{"dotfiles-local":{"source":{"source":"directory","path":"/tmp/dotfiles"}}}
JSON
  version="$(jq -r '.version' "$root/plugins/local-skills/.claude-plugin/plugin.json")"
  cache="$home/.claude/plugins/cache/dotfiles-local/local-skills/$version"
  mkdir -p "$cache/.claude-plugin" "$cache/skills/shared-skill"
  cp "$root/plugins/local-skills/.claude-plugin/plugin.json" "$cache/.claude-plugin/plugin.json"
  printf '%s\n' 'name: shared-skill' 'content: stale' > "$cache/skills/shared-skill/SKILL.md"
  jq -n --arg path "$cache" --arg version "$version" \
    '{version:2,plugins:{"local-skills@dotfiles-local":[{scope:"user",installPath:$path,version:$version}]}}' \
    > "$home/.claude/plugins/installed_plugins.json"
  cat > "$fakebin/curl" <<'SH'
#!/bin/bash
printf '%s\n' 'name: grill-me' > "${@: -1}"
SH
  cat > "$fakebin/claude" <<'SH'
#!/bin/bash
exit 0
SH
  make_executable "$fakebin/curl"
  make_executable "$fakebin/claude"

  run env HOME="$home" DOTFILES_DIR="$root" PATH="$fakebin:$PATH" \
    STUB_PLUGIN_DRIFT=1 bash "$REPO_ROOT/scripts/skills.sh" claude

  [ "$status" -ne 0 ]
  [[ "$output" == *"skill content drift"* ]]
}

@test "local plugin manifest versions are aligned and bumped beyond 0.1.0" {
  marketplace_version="$(jq -r '.plugins[] | select(.name == "local-skills") | .version' "$REPO_ROOT/.claude-plugin/marketplace.json")"
  claude_version="$(jq -r '.version' "$REPO_ROOT/plugins/local-skills/.claude-plugin/plugin.json")"
  codex_version="$(jq -r '.version' "$REPO_ROOT/plugins/local-skills/.codex-plugin/plugin.json")"

  [ "$marketplace_version" = "$claude_version" ]
  [ "$claude_version" = "$codex_version" ]
  [ "$claude_version" != "0.1.0" ]
}

@test "company overlay gate rejects local modifications even when HEAD matches gitlink" {
  root="$TMPDIR_TEST/company-gate-root"
  mkdir -p "$root/company"
  git -C "$root/company" init -q
  printf '%s\n' '#!/bin/bash' 'echo safe' > "$root/company/install.sh"
  git -C "$root/company" add install.sh
  git -C "$root/company" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm baseline
  git -C "$root" init -q
  git -C "$root" add company
  git -C "$root" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm 'pin company overlay'

  run env DOTFILES_DIR="$root" bash -c \
    'source "$1/scripts/lib/common.sh"; company_overlay_current "$DOTFILES_DIR"' _ "$REPO_ROOT"
  [ "$status" -eq 0 ]

  printf '%s\n' 'echo locally-modified' >> "$root/company/install.sh"
  run env DOTFILES_DIR="$root" bash -c \
    'source "$1/scripts/lib/common.sh"; company_overlay_current "$DOTFILES_DIR"' _ "$REPO_ROOT"
  [ "$status" -ne 0 ]
}

@test "company overlay gate fails closed when cleanliness cannot be queried" {
  root="$TMPDIR_TEST/company-status-fail-root"
  fakebin="$TMPDIR_TEST/company-status-fail-bin"
  mkdir -p "$root/company" "$fakebin"
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
case "$*" in
  *"rev-parse --is-inside-work-tree"*) exit 0 ;;
  *"ls-tree HEAD -- company"*) printf '%s\n' '160000 commit 1111111111111111111111111111111111111111 company'; exit 0 ;;
  *"company rev-parse HEAD"*) printf '%s\n' '1111111111111111111111111111111111111111'; exit 0 ;;
  *"company rev-parse --show-toplevel"*) printf '%s\n' "$DOTFILES_DIR/company"; exit 0 ;;
  *"company status --porcelain --untracked-files=normal"*) exit 7 ;;
esac
exit 1
SH
  make_executable "$fakebin/git"

  run env DOTFILES_DIR="$root" PATH="$fakebin:$PATH" bash -c \
    'source "$1/scripts/lib/common.sh"; company_overlay_current "$DOTFILES_DIR"' _ "$REPO_ROOT"

  [ "$status" -ne 0 ]
}

prepare_claude_fixture() {
  local root="$1" home="$2" fakebin="$3" mcp_json="$4"
  mkdir -p "$root/configs" "$root/scripts" "$home/.claude/plugins/session-wrap" \
    "$home/.local/share/ui-clone-skills/.claude-plugin" "$fakebin"
  printf '%s\n' "$mcp_json" > "$root/configs/mcp.json"
  cat > "$root/scripts/skills.sh" <<'SH'
#!/bin/bash
exit 0
SH
  cat > "$home/.local/share/ui-clone-skills/install.sh" <<'SH'
#!/bin/bash
exit 0
SH
  cat > "$fakebin/skills" <<'SH'
#!/bin/bash
exit 0
SH
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
exit 0
SH
  cat > "$fakebin/claude" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$CALL_LOG"
case "$1" in
  --version) printf '%s\n' '1.0.0'; exit 0 ;;
  update) exit 0 ;;
esac
if [ "$1 $2" = "mcp add-json" ] && { [ "$5" = "rollback-test" ] || [ "$5" = "new-test" ]; }; then
  case "$6" in
    *new.example*) printf '%s\n' 'simulated add failure' >&2; exit 55 ;;
  esac
fi
if [ "$1 $2 $5" = "mcp remove remove-loss-test" ]; then
  tmp="$HOME/.claude.json.tmp"
  jq 'del(.mcpServers["remove-loss-test"])' "$HOME/.claude.json" > "$tmp"
  mv "$tmp" "$HOME/.claude.json"
  exit 54
fi
if [ "$1 $2 $5" = "mcp add-json remove-loss-test" ]; then
  tmp="$HOME/.claude.json.tmp"
  jq --argjson entry "$6" '.mcpServers["remove-loss-test"] = $entry' "$HOME/.claude.json" > "$tmp"
  mv "$tmp" "$HOME/.claude.json"
  exit 0
fi
if [ "$1 $2 $5" = "mcp remove secret-test" ]; then
  tmp="$HOME/.claude.json.tmp"
  jq 'del(.mcpServers["secret-test"])' "$HOME/.claude.json" > "$tmp"
  mv "$tmp" "$HOME/.claude.json"
  exit 0
fi
if [ "$1 $2 $5" = "mcp add-json secret-test" ]; then
  tmp="$HOME/.claude.json.tmp"
  jq --argjson entry "$6" '.mcpServers["secret-test"] = $entry' "$HOME/.claude.json" > "$tmp"
  mv "$tmp" "$HOME/.claude.json"
  exit 0
fi
if [ "$1 $2 $5" = "mcp add-json leak-test" ]; then
  printf '%s\n' "$*" >&2
  exit 55
fi
exit 0
SH
  chmod +x "$root/scripts/skills.sh" \
    "$home/.local/share/ui-clone-skills/install.sh" \
    "$fakebin/skills" "$fakebin/git" "$fakebin/claude"
}

@test "Claude setup fails when the native installer does not produce a CLI" {
  root="$TMPDIR_TEST/claude-install-fail-root"
  home="$TMPDIR_TEST/claude-install-fail-home"
  fakebin="$TMPDIR_TEST/claude-install-fail-bin"
  mkdir -p "$root" "$home" "$fakebin"
  cat > "$fakebin/curl" <<'SH'
#!/bin/bash
exit 22
SH
  make_executable "$fakebin/curl"

  run env HOME="$home" DOTFILES_DIR="$root" PATH="$fakebin:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Claude Code is still unavailable after the native install attempt"* ]]
}

@test "Claude MCP registration fails when jq is absent" {
  root="$TMPDIR_TEST/claude-prereq-root"
  home="$TMPDIR_TEST/claude-prereq-home"
  fakebin="$TMPDIR_TEST/claude-prereq-bin"
  log="$TMPDIR_TEST/claude-prereq.log"
  prepare_claude_fixture "$root" "$home" "$fakebin" \
    '{"mcpServers":{"prereq-test":{"type":"http","url":"https://example.test"}}}'
  printf '%s\n' '{"mcpServers":{}}' > "$home/.claude.json"

  run env HOME="$home" DOTFILES_DIR="$root" \
    UI_CLONE_INSTALL_DIR="$home/.local/share/ui-clone-skills" \
    NON_INTERACTIVE=true PATH="$fakebin:/bin" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot register MCPs from $root/configs/mcp.json"* ]]
  run grep -Fq 'mcp add-json --scope user prereq-test' "$log"
  [ "$status" -ne 0 ]
}

@test "Claude MCP stores secret placeholders without rendering their values" {
  root="$TMPDIR_TEST/claude-missing-root"
  home="$TMPDIR_TEST/claude-missing-home"
  fakebin="$TMPDIR_TEST/claude-missing-bin"
  log="$TMPDIR_TEST/claude-missing.log"
  # shellcheck disable=SC2016 # literal fixture placeholder.
  prepare_claude_fixture "$root" "$home" "$fakebin" \
    '{"mcpServers":{"secret-test":{"type":"http","url":"https://example.test","headers":{"x-api-key":"$FIGMA_API_KEY"}}}}'
  cat > "$home/.claude.json" <<'JSON'
{"mcpServers":{"secret-test":{"type":"http","url":"https://working.example"}}}
JSON

  run env -u FIGMA_API_KEY HOME="$home" DOTFILES_DIR="$root" \
    UI_CLONE_INSTALL_DIR="$home/.local/share/ui-clone-skills" \
    NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -eq 0 ]
  run grep -Fq 'mcp remove --scope user secret-test' "$log"
  [ "$status" -eq 0 ]
  run grep -Fq 'mcp add-json --scope user secret-test' "$log"
  [ "$status" -eq 0 ]
  jq -e '.mcpServers["secret-test"].headers["x-api-key"] == "$FIGMA_API_KEY"' \
    "$home/.claude.json"
}

@test "Claude MCP rolls back the backed up entry when replacement add fails" {
  root="$TMPDIR_TEST/claude-rollback-root"
  home="$TMPDIR_TEST/claude-rollback-home"
  fakebin="$TMPDIR_TEST/claude-rollback-bin"
  log="$TMPDIR_TEST/claude-rollback.log"
  prepare_claude_fixture "$root" "$home" "$fakebin" \
    '{"mcpServers":{"rollback-test":{"type":"http","url":"https://new.example"}}}'
  cat > "$home/.claude.json" <<'JSON'
{"mcpServers":{"rollback-test":{"type":"http","url":"https://old.example"}}}
JSON

  run env HOME="$home" DOTFILES_DIR="$root" \
    UI_CLONE_INSTALL_DIR="$home/.local/share/ui-clone-skills" \
    NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  grep -Fq 'mcp remove --scope user rollback-test' "$log"
  grep -Fq 'mcp add-json --scope user rollback-test {"type":"http","url":"https://new.example"}' "$log"
  grep -Fq 'mcp add-json --scope user rollback-test {"type":"http","url":"https://old.example"}' "$log"
  [[ "$output" == *"restored and verified previous config"* ]]
}

@test "Claude MCP new registration failure exits nonzero and cleans partial state" {
  root="$TMPDIR_TEST/claude-new-fail-root"
  home="$TMPDIR_TEST/claude-new-fail-home"
  fakebin="$TMPDIR_TEST/claude-new-fail-bin"
  log="$TMPDIR_TEST/claude-new-fail.log"
  prepare_claude_fixture "$root" "$home" "$fakebin" \
    '{"mcpServers":{"new-test":{"type":"http","url":"https://new.example"}}}'
  printf '%s\n' '{"mcpServers":{}}' > "$home/.claude.json"

  run env HOME="$home" DOTFILES_DIR="$root" \
    UI_CLONE_INSTALL_DIR="$home/.local/share/ui-clone-skills" \
    NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  grep -Fq 'mcp add-json --scope user new-test {"type":"http","url":"https://new.example"}' "$log"
  grep -Fq 'mcp remove --scope user new-test' "$log"
  jq -e '.mcpServers == {}' "$home/.claude.json"
  [[ "$output" == *"Failed to register MCP: new-test"* ]]
}

@test "Claude MCP refuses a successful CLI exit without the JSON postcondition" {
  root="$TMPDIR_TEST/claude-postcondition-root"
  home="$TMPDIR_TEST/claude-postcondition-home"
  fakebin="$TMPDIR_TEST/claude-postcondition-bin"
  log="$TMPDIR_TEST/claude-postcondition.log"
  prepare_claude_fixture "$root" "$home" "$fakebin" \
    '{"mcpServers":{"lying-test":{"type":"http","url":"https://expected.example"}}}'
  printf '%s\n' '{"mcpServers":{}}' > "$home/.claude.json"

  run env HOME="$home" DOTFILES_DIR="$root" \
    UI_CLONE_INSTALL_DIR="$home/.local/share/ui-clone-skills" \
    NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Failed to verify registered MCP postcondition: lying-test"* ]]
  grep -Fq 'mcp remove --scope user lying-test' "$log"
}

@test "Claude MCP restores an entry when remove mutates config then exits nonzero" {
  root="$TMPDIR_TEST/claude-remove-loss-root"
  home="$TMPDIR_TEST/claude-remove-loss-home"
  fakebin="$TMPDIR_TEST/claude-remove-loss-bin"
  log="$TMPDIR_TEST/claude-remove-loss.log"
  prepare_claude_fixture "$root" "$home" "$fakebin" \
    '{"mcpServers":{"remove-loss-test":{"type":"http","url":"https://new.example"}}}'
  cat > "$home/.claude.json" <<'JSON'
{"mcpServers":{"remove-loss-test":{"type":"http","url":"https://old.example"}}}
JSON

  run env HOME="$home" DOTFILES_DIR="$root" \
    UI_CLONE_INSTALL_DIR="$home/.local/share/ui-clone-skills" \
    NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  jq -e '.mcpServers["remove-loss-test"].url == "https://old.example"' "$home/.claude.json"
  [[ "$output" == *"remove failed after mutating config; restored and verified"* ]]
}

@test "Claude MCP never echoes credential JSON from a failing CLI" {
  root="$TMPDIR_TEST/claude-redaction-root"
  home="$TMPDIR_TEST/claude-redaction-home"
  fakebin="$TMPDIR_TEST/claude-redaction-bin"
  log="$TMPDIR_TEST/claude-redaction.log"
  secret="super-private-mcp-value"
  prepare_claude_fixture "$root" "$home" "$fakebin" \
    "{\"mcpServers\":{\"leak-test\":{\"type\":\"http\",\"url\":\"https://example.test\",\"headers\":{\"x-api-key\":\"$secret\"}}}}"
  printf '%s\n' '{"mcpServers":{}}' > "$home/.claude.json"

  run env HOME="$home" DOTFILES_DIR="$root" \
    UI_CLONE_INSTALL_DIR="$home/.local/share/ui-clone-skills" \
    NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  [[ "$output" != *"$secret"* ]]
  [[ "$output" == *"CLI output suppressed"* ]]
}

@test "Codex upgrade dry-run previews the npm upgrade without executing tools" {
  root="$TMPDIR_TEST/codex-dry-root"
  home="$TMPDIR_TEST/codex-dry-home"
  fakebin="$TMPDIR_TEST/codex-dry-bin"
  log="$TMPDIR_TEST/codex-dry.log"
  mkdir -p "$root/configs/codex" "$root/scripts" "$home" "$fakebin"
  printf '%s\n' '# portable template' > "$root/configs/codex/config.toml"
  cat > "$root/scripts/skills.sh" <<'SH'
#!/bin/bash
exit 0
SH
  cat > "$fakebin/codex" <<'SH'
#!/bin/bash
printf '%s\n' "$0 $*" >> "$CALL_LOG"
exit 97
SH
  make_executable "$fakebin/codex"
  make_executable "$root/scripts/skills.sh"

  run env HOME="$home" CODEX_HOME="$home/.codex" DOTFILES_DIR="$root" \
    DRY_RUN=true UPGRADE=true NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/codex.sh"

  [ "$status" -eq 0 ]
  [[ "$output" == *"would: npm install -g @openai/codex@latest"* ]]
  [ ! -e "$log" ]
  [ ! -e "$home/.codex" ]
}

@test "Codex upgrade installs the latest Codex CLI through npm" {
  root="$TMPDIR_TEST/codex-root"
  home="$TMPDIR_TEST/codex-home"
  fakebin="$TMPDIR_TEST/codex-bin"
  log="$TMPDIR_TEST/codex.log"
  mkdir -p "$root/configs/codex" "$root/scripts" "$home/.codex" "$fakebin"
  printf '%s\n' '# portable template' > "$root/configs/codex/config.toml"
  cat > "$root/scripts/skills.sh" <<'SH'
#!/bin/bash
exit 0
SH
  cat > "$fakebin/codex" <<'SH'
#!/bin/bash
if [ "$1" = "--version" ]; then printf '%s\n' 'codex 1.0.0'; exit 0; fi
if [ "$1 $2" = "login status" ]; then exit 0; fi
exit 0
SH
  cat > "$fakebin/npm" <<'SH'
#!/bin/bash
printf 'npm %s\n' "$*" >> "$CALL_LOG"
exit 0
SH
  cat > "$fakebin/git" <<'SH'
#!/bin/bash
if [ "$1" = "clone" ]; then
  dest="${@: -1}"
  mkdir -p "$dest/skills/cmux"
  printf '%s\n' 'name: cmux' > "$dest/skills/cmux/SKILL.md"
  exit 0
fi
if [ "$1" = "-C" ] && [ "$3" = "sparse-checkout" ]; then
  mkdir -p "$2/skills/cmux"
  printf '%s\n' 'name: cmux' > "$2/skills/cmux/SKILL.md"
fi
exit 0
SH
  chmod +x "$root/scripts/skills.sh" "$fakebin/codex" "$fakebin/npm" "$fakebin/git"

  run env HOME="$home" CODEX_HOME="$home/.codex" DOTFILES_DIR="$root" \
    UPGRADE=true NON_INTERACTIVE=true PATH="$fakebin:$PATH" CALL_LOG="$log" \
    bash "$REPO_ROOT/scripts/codex.sh"

  [ "$status" -eq 0 ]
  grep -Fq 'npm install -g @openai/codex@latest' "$log"
  run grep -Ei 'omx|oh-my-codex' "$log"
  [ "$status" -ne 0 ]
}
