#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  TEST_ROOT="$(mktemp -d)"
  TEST_BIN="$TEST_ROOT/bin"
  COMPLETION_LOG="$TEST_ROOT/completion.log"
  mkdir -p "$TEST_BIN"
  : > "$COMPLETION_LOG"

  cat > "$TEST_BIN/dotfiles-auth" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$COMPLETION_LOG"
if [ "${1:-}" != "catalog" ] || [ -n "${AUTH_CATALOG_FAIL:-}" ]; then
  exit 1
fi
printf 'name\tkind\troute\tbinding\tstore\n'
printf 'exa\tenv-token\tpersonal-ro\tEXA_API_KEY\tkeychain:exa\n'
printf 'linear\tenv-token\twork-ro\tLINEAR_API_KEY\tkeychain:linear\n'
printf 'linkedin-session\tbrowser-session\tunscoped\t-\tbrowser\n'
SH
  chmod +x "$TEST_BIN/dotfiles-auth"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "dotfiles-auth completion loads registered env-token names from catalog" {
  completion="$REPO_ROOT/configs/zsh-completions/_dotfiles-auth"

  run env PATH="$TEST_BIN:/usr/bin:/bin" COMPLETION_LOG="$COMPLETION_LOG" \
    zsh -fc 'source "$1"; _dotfiles_auth_credential_names' _ "$completion"

  [ "$status" -eq 0 ]
  [ "$output" = $'exa\nlinear' ]
  [ "$(cat "$COMPLETION_LOG")" = "catalog" ]
  [[ "$output" != *"linkedin-session"* ]]
}

@test "dotfiles-auth completion fails quiet when catalog is unavailable" {
  completion="$REPO_ROOT/configs/zsh-completions/_dotfiles-auth"

  run env PATH="$TEST_BIN:/usr/bin:/bin" COMPLETION_LOG="$COMPLETION_LOG" \
    AUTH_CATALOG_FAIL=1 zsh -fc \
    'source "$1"; _dotfiles_auth_credential_names; print -r -- after' \
    _ "$completion"

  [ "$status" -eq 0 ]
  [ "$output" = "after" ]
  [ "$(cat "$COMPLETION_LOG")" = "catalog" ]
}

@test "dotfiles install owns and registers the completion after Oh My Zsh initializes" {
  completion="$REPO_ROOT/configs/zsh-completions/_dotfiles-auth"
  [ -f "$completion" ]
  zsh -n "$completion"

  grep -Fq 'configs/zsh-completions/_dotfiles-auth' "$REPO_ROOT/install.sh"
  grep -Fq '.local/share/zsh/site-functions/_dotfiles-auth' "$REPO_ROOT/install.sh"
  grep -Fq "_values 'setup scope' all core personal work social" "$completion"

  source_line="$(grep -n '.local/share/zsh/site-functions/_dotfiles-auth' "$REPO_ROOT/configs/.zshrc" | head -1 | cut -d: -f1)"
  omz_line="$(grep -n 'source "$ZSH/oh-my-zsh.sh"' "$REPO_ROOT/configs/.zshrc" | head -1 | cut -d: -f1)"
  [ -n "$source_line" ]
  [ "$source_line" -gt "$omz_line" ]

  run zsh -fc \
    'autoload -Uz compinit; compinit -D; source "$1"; print -r -- "${_comps[dotfiles-auth]-}"' \
    _ "$completion"
  [ "$status" -eq 0 ]
  [ "$output" = "_dotfiles-auth" ]
}
