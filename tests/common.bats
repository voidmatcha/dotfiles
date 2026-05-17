#!/usr/bin/env bats
# Tests for scripts/lib/common.sh

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  COMMON="$REPO_ROOT/scripts/lib/common.sh"
  TMPDIR_TEST="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

@test "common.sh sources cleanly with defaults" {
  run bash -c "source '$COMMON' && echo \"\$DOTFILES_DIR|\$DRY_RUN|\$TAG\""
  [ "$status" -eq 0 ]
  [[ "$output" == *"|false|dotfiles" ]]
}

@test "common.sh is idempotent (guard against double-source)" {
  run bash -c "source '$COMMON' && source '$COMMON' && echo ok"
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

@test "info/warn/error tag the output" {
  run bash -c "TAG=mytag; source '$COMMON'; info hello; warn careful; error boom"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[mytag]"*"hello"* ]]
  [[ "$output" == *"[mytag]"*"careful"* ]]
  [[ "$output" == *"[mytag]"*"boom"* ]]
}

@test "run_or_dry executes when DRY_RUN=false" {
  out="$TMPDIR_TEST/marker"
  run bash -c "DRY_RUN=false; source '$COMMON'; run_or_dry 'touch marker' touch '$out'"
  [ "$status" -eq 0 ]
  [ -f "$out" ]
}

@test "run_or_dry skips and announces in dry-run" {
  out="$TMPDIR_TEST/marker"
  run bash -c "DRY_RUN=true; source '$COMMON'; run_or_dry 'touch marker' touch '$out'"
  [ "$status" -eq 0 ]
  [ ! -f "$out" ]
  [[ "$output" == *"[dry-run]"* ]]
}

@test "link_file creates a symlink" {
  src="$TMPDIR_TEST/src"; dst="$TMPDIR_TEST/dst"
  echo hi > "$src"
  run bash -c "DRY_RUN=false; source '$COMMON'; link_file '$src' '$dst'"
  [ "$status" -eq 0 ]
  [ -L "$dst" ]
  [ "$(readlink "$dst")" = "$src" ]
}

@test "link_file backs up existing real file before linking" {
  src="$TMPDIR_TEST/src"; dst="$TMPDIR_TEST/dst"
  echo new > "$src"
  echo old > "$dst"
  run bash -c "DRY_RUN=false; source '$COMMON'; link_file '$src' '$dst'"
  [ "$status" -eq 0 ]
  [ -L "$dst" ]
  [ -f "${dst}.backup" ]
  [ "$(cat "${dst}.backup")" = "old" ]
}

@test "link_file does not overwrite an existing backup" {
  src="$TMPDIR_TEST/src"; dst="$TMPDIR_TEST/dst"
  echo new > "$src"
  echo old > "$dst"
  echo previous > "${dst}.backup"

  run bash -c "DRY_RUN=false; source '$COMMON'; link_file '$src' '$dst'"

  [ "$status" -eq 0 ]
  [ -L "$dst" ]
  [ "$(cat "${dst}.backup")" = "previous" ]
  [ -f "${dst}.backup.1" ]
  [ "$(cat "${dst}.backup.1")" = "old" ]
}

@test "link_file is a no-op in dry-run" {
  src="$TMPDIR_TEST/src"; dst="$TMPDIR_TEST/dst"
  echo hi > "$src"
  run bash -c "DRY_RUN=true; source '$COMMON'; link_file '$src' '$dst'"
  [ "$status" -eq 0 ]
  [ ! -e "$dst" ]
}

@test "ensure_dir creates a directory" {
  dir="$TMPDIR_TEST/new-dir"
  run bash -c "DRY_RUN=false; source '$COMMON'; ensure_dir '$dir'"
  [ "$status" -eq 0 ]
  [ -d "$dir" ]
}

@test "ensure_dir is a no-op in dry-run" {
  dir="$TMPDIR_TEST/dry-dir"
  run bash -c "DRY_RUN=true; source '$COMMON'; ensure_dir '$dir'"
  [ "$status" -eq 0 ]
  [ ! -e "$dir" ]
  [[ "$output" == *"[dry-run] mkdir -p"* ]]
}

@test "with_timeout passes through exit code on success" {
  run bash -c "source '$COMMON'; with_timeout 5 true"
  [ "$status" -eq 0 ]
  run bash -c "source '$COMMON'; with_timeout 5 false"
  [ "$status" -ne 0 ]
}

@test "with_timeout kills slow command (exit 142 on SIGALRM)" {
  run bash -c "source '$COMMON'; with_timeout 1 sleep 5"
  # SIGALRM (perl alarm) terminates the process; exit code is 128+14=142.
  [ "$status" -eq 142 ]
}

@test "json_entry_exists returns true when filter matches" {
  cat > "$TMPDIR_TEST/state.json" <<'JSON'
{ "plugins": { "alpha@market": {}, "beta@market": {} } }
JSON
  run bash -c "source '$COMMON'; json_entry_exists '$TMPDIR_TEST/state.json' '.plugins | has(\$p)' --arg p 'alpha@market'"
  [ "$status" -eq 0 ]
}

@test "json_entry_exists returns false when filter does not match" {
  cat > "$TMPDIR_TEST/state.json" <<'JSON'
{ "plugins": { "alpha@market": {} } }
JSON
  run bash -c "source '$COMMON'; json_entry_exists '$TMPDIR_TEST/state.json' '.plugins | has(\$p)' --arg p 'missing@market'"
  [ "$status" -ne 0 ]
}

@test "json_entry_exists is injection-safe via --arg" {
  cat > "$TMPDIR_TEST/state.json" <<'JSON'
{ "plugins": { "real": {} } }
JSON
  # Hostile value with double-quote + jq operator. Without --arg this would
  # break the filter; with --arg it's treated as a literal string -> no match.
  evil='evil"; "any string here"'
  run bash -c "source '$COMMON'; json_entry_exists '$TMPDIR_TEST/state.json' '.plugins | has(\$p)' --arg p '$evil'"
  [ "$status" -ne 0 ]
}

@test "json_entry_exists returns false when file is missing" {
  run bash -c "source '$COMMON'; json_entry_exists '$TMPDIR_TEST/nope.json' '.'"
  [ "$status" -ne 0 ]
}
