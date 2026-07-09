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

@test "every local skill frontmatter description is validator-safe" {
  python3 - "$REPO_ROOT/plugins/local-skills/skills" <<'PY'
import re
import sys
from pathlib import Path

for skill in sorted(Path(sys.argv[1]).glob("*/SKILL.md")):
    text = skill.read_text(encoding="utf-8")
    match = re.search(r"\A---\n(.*?)\n---(?:\n|\Z)", text, re.S)
    assert match, f"missing frontmatter: {skill}"
    desc = re.search(r'^description:\s*["\']?(.*?)["\']?\s*$', match.group(1), re.M)
    assert desc, f"missing description: {skill}"
    assert "<" not in desc.group(1) and ">" not in desc.group(1), f"angle bracket in description: {skill}"
PY
}

@test "doctor is clean at the CI shellcheck warning threshold" {
  command -v shellcheck >/dev/null 2>&1 || skip "shellcheck unavailable"
  run shellcheck -S warning -e SC1091 -x "$REPO_ROOT/scripts/doctor.sh"
  [ "$status" -eq 0 ]
}

@test "secret scan covers the worktree and an explicit outgoing history range" {
  home="$TMPDIR_TEST/home"
  bin="$TMPDIR_TEST/bin"
  mkdir -p "$home" "$bin"
  cat > "$bin/gitleaks" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$HOME/gitleaks-args.txt"
SH
  chmod +x "$bin/gitleaks"

  run env HOME="$home" DOTFILES_DIR="$REPO_ROOT" PATH="$bin:/usr/bin:/bin" \
    GITLEAKS_LOG_OPTS="HEAD~1..HEAD" bash "$REPO_ROOT/scripts/secret-scan.sh" --required

  [ "$status" -eq 0 ]
  grep -Fqx "detect --source $REPO_ROOT --config $REPO_ROOT/.gitleaks-worktree.toml --no-git --redact --verbose" "$home/gitleaks-args.txt"
  grep -Fqx "git $REPO_ROOT --config $REPO_ROOT/.gitleaks.toml --log-opts HEAD~1..HEAD --redact --verbose" "$home/gitleaks-args.txt"
}

@test "secret scan rejects a secret committed and removed before push" {
  command -v gitleaks >/dev/null 2>&1 || skip "gitleaks unavailable"
  repo="$TMPDIR_TEST/outgoing-secret-repo"
  remote="$TMPDIR_TEST/outgoing-secret.git"
  mkdir -p "$repo/scripts/lib"
  cp "$REPO_ROOT/scripts/secret-scan.sh" "$repo/scripts/secret-scan.sh"
  cp "$REPO_ROOT/scripts/lib/common.sh" "$repo/scripts/lib/common.sh"
  cp "$REPO_ROOT/.gitleaks.toml" "$repo/.gitleaks.toml"
  cp "$REPO_ROOT/.gitleaks-worktree.toml" "$repo/.gitleaks-worktree.toml"

  git init -q --bare "$remote"
  git -C "$repo" init -q
  git -C "$repo" remote add origin "$remote"
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    add scripts .gitleaks.toml
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm baseline
  git -C "$repo" push -q -u origin HEAD:main

  printf 'AWS_ACCESS_KEY_ID=%s%s\n' 'AKIA' 'ABCDEFGHIJKLMNOP' > "$repo/temporary.env"
  git -C "$repo" add temporary.env
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm 'add temporary credential'
  git -C "$repo" rm -q temporary.env
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm 'remove temporary credential'

  run env DOTFILES_DIR="$repo" bash "$repo/scripts/secret-scan.sh" --required

  [ "$status" -ne 0 ]
  [[ "$output" == *"repository commit-history scan"* ]]
}

@test "history scan does not allowlist a force-committed runtime path" {
  command -v gitleaks >/dev/null 2>&1 || skip "gitleaks unavailable"
  repo="$TMPDIR_TEST/ignored-path-secret-repo"
  remote="$TMPDIR_TEST/ignored-path-secret.git"
  mkdir -p "$repo/scripts/lib"
  cp "$REPO_ROOT/scripts/secret-scan.sh" "$repo/scripts/secret-scan.sh"
  cp "$REPO_ROOT/scripts/lib/common.sh" "$repo/scripts/lib/common.sh"
  cp "$REPO_ROOT/.gitleaks.toml" "$repo/.gitleaks.toml"
  cp "$REPO_ROOT/.gitleaks-worktree.toml" "$repo/.gitleaks-worktree.toml"

  git init -q --bare "$remote"
  git -C "$repo" init -q
  git -C "$repo" remote add origin "$remote"
  printf '%s\n' '.omx/' > "$repo/.gitignore"
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    add scripts .gitleaks.toml .gitleaks-worktree.toml .gitignore
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm baseline
  git -C "$repo" push -q -u origin HEAD:main

  mkdir -p "$repo/.omx"
  printf 'AWS_ACCESS_KEY_ID=%s%s\n' 'AKIA' 'ABCDEFGHIJKLMNOP' > "$repo/.omx/credential.env"
  git -C "$repo" add -f .omx/credential.env
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm 'accidentally commit runtime credential'

  run env DOTFILES_DIR="$repo" bash "$repo/scripts/secret-scan.sh" --required

  [ "$status" -ne 0 ]
  [[ "$output" == *"repository commit-history scan"* ]]
}

@test "default history scan rejects a secret on a non-checked-out branch" {
  command -v gitleaks >/dev/null 2>&1 || skip "gitleaks unavailable"
  repo="$TMPDIR_TEST/side-branch-secret-repo"
  mkdir -p "$repo/scripts/lib"
  cp "$REPO_ROOT/scripts/secret-scan.sh" "$repo/scripts/secret-scan.sh"
  cp "$REPO_ROOT/scripts/lib/common.sh" "$repo/scripts/lib/common.sh"
  cp "$REPO_ROOT/.gitleaks.toml" "$repo/.gitleaks.toml"
  cp "$REPO_ROOT/.gitleaks-worktree.toml" "$repo/.gitleaks-worktree.toml"

  git -C "$repo" init -q
  git -C "$repo" add scripts .gitleaks.toml .gitleaks-worktree.toml
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm baseline
  original_branch="$(git -C "$repo" branch --show-current)"
  git -C "$repo" checkout -qb secret-side
  printf 'AWS_ACCESS_KEY_ID=%s%s\n' 'AKIA' 'ABCDEFGHIJKLMNOP' > "$repo/side-secret.env"
  git -C "$repo" add side-secret.env
  git -C "$repo" -c user.name=test -c user.email=test@example.com \
    -c commit.gpgsign=false commit -qm 'secret only on side branch'
  git -C "$repo" checkout -q "$original_branch"

  run env DOTFILES_DIR="$repo" bash "$repo/scripts/secret-scan.sh" --required

  [ "$status" -ne 0 ]
  [[ "$output" == *"repository commit-history scan (--all)"* ]]
}

@test "quick verifier executes Python unit tests" {
  run bash "$REPO_ROOT/scripts/verify.sh" --quick
  [ "$status" -eq 0 ]
  [[ "$output" == *"[verify] Python unit tests"* ]]
}

@test "full verifier fails closed when Bats is unavailable" {
  home="$TMPDIR_TEST/no-bats-home"
  bin="$TMPDIR_TEST/no-bats-bin"
  mkdir -p "$home" "$bin"
  cat > "$bin/shellcheck" <<'SH'
#!/bin/sh
exit 0
SH
  chmod +x "$bin/shellcheck"

  run env HOME="$home" DOTFILES_DIR="$REPO_ROOT" PATH="$bin:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/verify.sh" --full

  [ "$status" -ne 0 ]
  [[ "$output" == *"--full requires bats"* ]]
}

@test "full verifier fails closed when ShellCheck is unavailable" {
  home="$TMPDIR_TEST/no-shellcheck-home"
  mkdir -p "$home"

  run env HOME="$home" DOTFILES_DIR="$REPO_ROOT" PATH="/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/verify.sh" --full

  [ "$status" -ne 0 ]
  [[ "$output" == *"--full requires shellcheck"* ]]
}

@test "pinned upstream skill download failure is nonzero and preserves the installed copy" {
  home="$TMPDIR_TEST/skills-download-home"
  codex_home="$TMPDIR_TEST/skills-download-codex"
  bin="$TMPDIR_TEST/skills-download-bin"
  mkdir -p "$home" "$codex_home/skills/grill-me" "$bin"
  printf '%s\n' 'previous-known-good' > "$codex_home/skills/grill-me/SKILL.md"
  cat > "$bin/curl" <<'SH'
#!/bin/sh
exit 22
SH
  chmod +x "$bin/curl"

  run env HOME="$home" CODEX_HOME="$codex_home" DOTFILES_DIR="$REPO_ROOT" \
    PATH="$bin:/usr/bin:/bin" bash "$REPO_ROOT/scripts/skills.sh" codex

  [ "$status" -ne 0 ]
  [[ "$output" == *"Failed upstream Codex skill download: grill-me"* ]]
  [ "$(cat "$codex_home/skills/grill-me/SKILL.md")" = "previous-known-good" ]
}

@test "Codex skill install fails when the declared local source directory is absent" {
  root="$TMPDIR_TEST/missing-local-skills-root"
  home="$TMPDIR_TEST/missing-local-skills-home"
  codex_home="$TMPDIR_TEST/missing-local-skills-codex"
  bin="$TMPDIR_TEST/missing-local-skills-bin"
  mkdir -p "$root" "$home" "$codex_home" "$bin"
  cat > "$bin/curl" <<'SH'
#!/bin/bash
dest="${@: -1}"
case "$*" in
  *figma-implement-design*) name=figma-implement-design ;;
  *) name=grill-me ;;
esac
printf '%s\n' "name: $name" > "$dest"
SH
  chmod +x "$bin/curl"

  run env HOME="$home" CODEX_HOME="$codex_home" DOTFILES_DIR="$root" \
    PATH="$bin:/usr/bin:/bin" bash "$REPO_ROOT/scripts/skills.sh" codex

  [ "$status" -ne 0 ]
  [[ "$output" == *"local skills directory not found: $root/plugins/local-skills/skills"* ]]
}

@test "Claude skill install fails when the required local plugin cannot be registered" {
  home="$TMPDIR_TEST/missing-claude-home"
  bin="$TMPDIR_TEST/missing-claude-bin"
  mkdir -p "$home" "$bin"
  ln -s "$(command -v jq)" "$bin/jq"
  cat > "$bin/curl" <<'SH'
#!/bin/bash
printf '%s\n' 'name: grill-me' > "${@: -1}"
SH
  chmod +x "$bin/curl"

  run env HOME="$home" DOTFILES_DIR="$REPO_ROOT" PATH="$bin:/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/skills.sh" claude

  [ "$status" -ne 0 ]
  [[ "$output" == *"claude not found; cannot install the local Claude plugin"* ]]
}

@test "Claude MCP dry-run rejects non-object entries without exposing their value" {
  root="$TMPDIR_TEST/claude-mcp-shape-root"
  home="$TMPDIR_TEST/claude-mcp-shape-home"
  secret="must-not-appear-in-dry-run"
  mkdir -p "$root/configs" "$home"
  printf '{"mcpServers":{"invalid":"%s"}}\n' "$secret" > "$root/configs/mcp.json"

  run env HOME="$home" DOTFILES_DIR="$root" DRY_RUN=true PATH="/usr/bin:/bin" \
    bash "$REPO_ROOT/scripts/claude.sh"

  [ "$status" -ne 0 ]
  [[ "$output" == *"invalid MCP configuration"* ]]
  [[ "$output" != *"$secret"* ]]
}
