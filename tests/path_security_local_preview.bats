#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  PREVIEW_SCRIPT="$REPO_ROOT/plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh"
  TMPDIR_TEST="$(mktemp -d)"
  TMPDIR_TEST="$(cd "$TMPDIR_TEST" && pwd -P)"
  TEST_HOME="$TMPDIR_TEST/home"
  TEST_STATE_DIR="$TMPDIR_TEST/state"
  TEST_SITE="$TMPDIR_TEST/site"
  mkdir -p "$TEST_HOME" "$TEST_SITE"
  printf 'preview-ok\n' > "$TEST_SITE/index.html"
  PREVIEW_PID=""
  UNRELATED_PID=""

  # Homebrew installs tmux outside this path on macOS. Keeping tmux out of PATH
  # exercises the PID-file lifecycle deterministically.
  export PATH="/usr/bin:/bin"
  export HOME="$TEST_HOME"
  export LOCAL_PREVIEW_STATE_DIR="$TEST_STATE_DIR"
}

teardown() {
  if [ -n "$PREVIEW_PID" ] && kill -0 "$PREVIEW_PID" 2>/dev/null; then
    kill "$PREVIEW_PID" 2>/dev/null || true
  fi
  if [ -n "$UNRELATED_PID" ] && kill -0 "$UNRELATED_PID" 2>/dev/null; then
    kill "$UNRELATED_PID" 2>/dev/null || true
  fi
  rm -rf "$TMPDIR_TEST"
}

free_port() {
  python3 - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

process_started_at() {
  ps -p "$1" -o lstart= | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

write_selective_curl() {
  local bin="$1"
  cat > "$bin/curl" <<'SH'
#!/bin/bash
url=""
for arg in "$@"; do
  case "$arg" in http://*|https://*) url="$arg" ;; esac
done
case "$url" in
  http://127.0.0.1:*|http://\[::1\]:*) exec /usr/bin/curl "$@" ;;
  http://node.test.ts.net:*) exit 0 ;;
  *) exit 22 ;;
esac
SH
  chmod +x "$bin/curl"
}

write_fake_tailscale() {
  local bin="$1"
  cat > "$bin/tailscale" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$TS_LOG"
if [ "$1 $2" = "status --json" ]; then
  printf '%s\n' '{"Self":{"DNSName":"node.test.ts.net."}}'
  exit 0
fi
if [ "$1 $2 $3" = "serve status --json" ]; then
  mode="absent"
  [ ! -f "$TS_MODE" ] || mode="$(cat "$TS_MODE")"
  if [ "$mode" = "absent" ] || [ ! -f "$TS_STATE" ]; then
    printf '%s\n' '{}'
    exit 0
  fi
  port="$(cat "$TS_STATE")"
  backend="http://127.0.0.1:$port"
  [ "$mode" != "foreign" ] || backend="http://127.0.0.1:9999"
  printf '{"TCP":{"%s":{"HTTP":true}},"Web":{"node.test.ts.net:%s":{"Handlers":{"/":{"Proxy":"%s"}}}}}\n' \
    "$port" "$port" "$backend"
  exit 0
fi
if [ "$1" = "serve" ]; then
  port=""
  for arg in "$@"; do
    case "$arg" in --http=*) port="${arg#--http=}" ;; esac
  done
  if [ "${!#}" = "off" ]; then
    [ "${FAIL_OFF:-0}" != "1" ] || exit 9
    rm -f "$TS_STATE"
    printf '%s\n' absent > "$TS_MODE"
    exit 0
  fi
  printf '%s\n' "$port" > "$TS_STATE"
  printf '%s\n' "${POST_MAPPING_MODE:-owned}" > "$TS_MODE"
  exit 0
fi
exit 1
SH
  chmod +x "$bin/tailscale"
}

@test "local preview uses private JSON state and completes a normal start/status/stop lifecycle" {
  port="$(free_port)"

  run "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port"
  [ "$status" -eq 0 ]
  [[ "$output" == *"STATUS=ok"* ]]
  [[ "$output" == *"PORT=$port"* ]]
  [[ "$output" == *"STOP_COMMAND=$PREVIEW_SCRIPT stop --port $port"* ]]
  [[ "$output" != *"STOP_COMMAND=tmux kill-session"* ]]

  state_file="$TEST_STATE_DIR/local-preview-$port.json"
  pid_file="$TEST_STATE_DIR/local-preview-$port.pid"
  [ -f "$state_file" ]
  [ ! -L "$state_file" ]
  [ -f "$pid_file" ]
  PREVIEW_PID="$(cat "$pid_file")"

  run python3 - "$TEST_STATE_DIR" "$state_file" "$pid_file" <<'PY'
import json
import os
import stat
import sys

state_dir, state_file, pid_file = sys.argv[1:]
assert stat.S_IMODE(os.stat(state_dir).st_mode) == 0o700
assert stat.S_IMODE(os.stat(state_file).st_mode) == 0o600
with open(state_file, encoding="utf-8") as handle:
    state = json.load(handle)
assert state["port"] > 0
assert state["schema_version"] == 2
assert state["process_mode"] == "pid"
assert state["process_pid"] == int(open(pid_file, encoding="utf-8").read())
assert state["process_started_at"]
PY
  [ "$status" -eq 0 ]

  run "$PREVIEW_SCRIPT" status --port "$port"
  [ "$status" -eq 0 ]
  [[ "$output" == *"STATUS=ok"* ]]
  [[ "$output" == *"ROOT=$TEST_SITE"* ]]

  run "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  [[ "$output" == *"STOPPED=1"* ]]

  run kill -0 "$PREVIEW_PID"
  [ "$status" -ne 0 ]
  PREVIEW_PID=""
}

@test "tmux-mode output exposes only the ownership-verified stop helper" {
  port="$(free_port)"
  fakebin="$TMPDIR_TEST/tmux-bin"
  tmux_state="$TMPDIR_TEST/tmux-state"
  mkdir -p "$fakebin" "$tmux_state"
  cat > "$fakebin/tmux" <<'SH'
#!/bin/bash
set -euo pipefail

session_file() {
  printf '%s/%s' "$TMUX_TEST_STATE" "$1"
}

case "${1:-}" in
  new-session)
    session="$4"
    runner="$5"
    nohup "$runner" >/dev/null 2>&1 &
    pid=$!
    printf 'fixture:%s\n' "$pid" > "$(session_file "$session")"
    ;;
  has-session)
    session="$3"
    file="$(session_file "$session")"
    [ -f "$file" ] || exit 1
    pid="$(cut -d: -f2 "$file")"
    kill -0 "$pid" 2>/dev/null
    ;;
  display-message)
    session="$4"
    file="$(session_file "$session")"
    [ -f "$file" ] || exit 1
    cat "$file"
    ;;
  kill-session)
    session="$3"
    file="$(session_file "$session")"
    [ -f "$file" ] || exit 1
    pid="$(cut -d: -f2 "$file")"
    kill "$pid" 2>/dev/null || true
    rm -f "$file"
    ;;
  *)
    exit 2
    ;;
esac
SH
  chmod +x "$fakebin/tmux"

  run env PATH="$fakebin:$PATH" TMUX_TEST_STATE="$tmux_state" \
    "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port"

  [ "$status" -eq 0 ]
  [[ "$output" == *"PROCESS_MODE=tmux"* ]]
  [[ "$output" == *"STOP_COMMAND=$PREVIEW_SCRIPT stop --port $port"* ]]
  [[ "$output" != *"STOP_COMMAND=tmux kill-session"* ]]

  run env PATH="$fakebin:$PATH" TMUX_TEST_STATE="$tmux_state" \
    "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  [[ "$output" == *"STOPPED=1"* ]]
}

@test "reported stop command is absolute, quoted, and runnable from another cwd" {
  port="$(free_port)"
  helper_dir="$TMPDIR_TEST/helper dir"
  copied_helper="$helper_dir/local preview.sh"
  mkdir -p "$helper_dir"
  cp "$PREVIEW_SCRIPT" "$copied_helper"
  chmod +x "$copied_helper"

  run "$copied_helper" start --path "$TEST_SITE" --port "$port"
  [ "$status" -eq 0 ]
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"
  stop_command="$(printf '%s\n' "$output" | sed -n 's/^STOP_COMMAND=//p')"
  [[ "$stop_command" == /* ]]
  [[ "$stop_command" == *"helper\\ dir/local\\ preview.sh stop --port $port"* ]]

  run bash -c 'cd "$1" && bash -c "$2"' _ "$TEST_HOME" "$stop_command"
  [ "$status" -eq 0 ]
  [[ "$output" == *"STOPPED=1"* ]]
  run kill -0 "$PREVIEW_PID"
  [ "$status" -ne 0 ]
  PREVIEW_PID=""
}

@test "local preview never executes shell syntax from legacy or malformed state" {
  port="$(free_port)"
  marker="$TMPDIR_TEST/state-was-executed"
  mkdir -p "$TEST_STATE_DIR"

  cat > "$TEST_STATE_DIR/local-preview-$port.env" <<EOF
ROOT=\$(touch "$marker")
TARGET=/tmp
TARGET_TYPE=directory
URL_PATH=/
PROCESS_MODE=pid
BIND_ADDR=127.0.0.1
TAILSCALE_SERVE_ENABLED=0
TAILSCALE_SERVE_BASE_URL=
EOF
  cat > "$TEST_STATE_DIR/local-preview-$port.json" <<EOF
ROOT=\$(touch "$marker")
EOF

  run "$PREVIEW_SCRIPT" status --port "$port"
  [ "$status" -eq 0 ]
  [ ! -e "$marker" ]
}

@test "local preview rejects a symlinked state file instead of trusting its target" {
  port="$(free_port)"
  mkdir -p "$TEST_STATE_DIR"
  external="$TMPDIR_TEST/external-state.json"
  cat > "$external" <<EOF
{"schema_version":1,"port":$port,"root":"/attacker","target":"/attacker","target_type":"directory","url_path":"/","process_mode":"pid","bind_addr":"127.0.0.1","tailscale_serve_enabled":false,"tailscale_serve_base_url":""}
EOF
  ln -s "$external" "$TEST_STATE_DIR/local-preview-$port.json"

  run "$PREVIEW_SCRIPT" status --port "$port"
  [ "$status" -eq 0 ]
  [[ "$output" != *"ROOT=/attacker"* ]]
  [ -L "$TEST_STATE_DIR/local-preview-$port.json" ]
}

@test "local preview fails closed on an untrusted pid file and preserves evidence" {
  port="$(free_port)"
  mkdir -p "$TEST_STATE_DIR"
  sleep 30 &
  UNRELATED_PID="$!"
  printf '%s\n' "$UNRELATED_PID" > "$TEST_STATE_DIR/local-preview-$port.pid"

  run "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -ne 0 ]
  [[ "$output" == *"STOPPED=0"* ]]
  [ -f "$TEST_STATE_DIR/local-preview-$port.pid" ]
  run kill -0 "$UNRELATED_PID"
  [ "$status" -eq 0 ]
}

@test "local preview default state directory is per-user and mode 0700" {
  port="$(free_port)"
  unset LOCAL_PREVIEW_STATE_DIR
  unset XDG_STATE_HOME

  run "$PREVIEW_SCRIPT" status --port "$port"
  [ "$status" -eq 0 ]

  default_state_dir="$HOME/.local/state/local-preview-server"
  [ -d "$default_state_dir" ]
  run python3 - "$default_state_dir" <<'PY'
import os
import stat
import sys

assert stat.S_IMODE(os.stat(sys.argv[1]).st_mode) == 0o700
PY
  [ "$status" -eq 0 ]
}

@test "single-file preview isolates the requested file from sibling content" {
  port="$(free_port)"
  file_site="$TMPDIR_TEST/file-site"
  mkdir -p "$file_site"
  printf '%s\n' public-report > "$file_site/report.html"
  printf '%s\n' sibling-secret > "$file_site/private.txt"

  run "$PREVIEW_SCRIPT" start --path "$file_site/report.html" --port "$port"
  [ "$status" -eq 0 ]
  url="$(printf '%s\n' "$output" | awk -F= '$1 == "LOCAL_URL" {print $2; exit}')"
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"

  run /usr/bin/curl -fsS "$url"
  [ "$status" -eq 0 ]
  [[ "$output" == *"public-report"* ]]
  run /usr/bin/curl -fsS "${url%/*}/private.txt"
  [ "$status" -ne 0 ]

  serving_root="$(python3 - "$TEST_STATE_DIR/local-preview-$port.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["root"])
PY
)"
  rm "$serving_root/report.html"
  run "$PREVIEW_SCRIPT" status --port "$port"
  [ "$status" -eq 0 ]
  [[ "$output" == *"STATUS=degraded"* ]]

  run "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  [ ! -e "$TEST_STATE_DIR/local-preview-$port-root" ]
  PREVIEW_PID=""
}

@test "stop preserves state and fails when a live process identity is corrupted" {
  port="$(free_port)"
  run "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port"
  [ "$status" -eq 0 ]
  state="$TEST_STATE_DIR/local-preview-$port.json"
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"
  python3 - "$state" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
data["process_started_at"] = "forged-start-signature"
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
PY

  run "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -ne 0 ]
  [[ "$output" == *"STATUS=error"* ]]
  [[ "$output" == *"STOPPED=0"* ]]
  [ -f "$state" ]
  run kill -0 "$PREVIEW_PID"
  [ "$status" -eq 0 ]
}

@test "JSON process identity remains authoritative when the pid file is missing" {
  port="$(free_port)"
  run "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port"
  [ "$status" -eq 0 ]
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"
  rm "$TEST_STATE_DIR/local-preview-$port.pid"

  run "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  [[ "$output" == *"STOPPED=1"* ]]
  run kill -0 "$PREVIEW_PID"
  [ "$status" -ne 0 ]
  PREVIEW_PID=""
}

@test "failed exact local URL verification cleans the spawned process and state" {
  port="$(free_port)"
  fakebin="$TMPDIR_TEST/failing-curl-bin"
  captured_pid="$TMPDIR_TEST/failed-start.pid"
  mkdir -p "$fakebin"
  cat > "$fakebin/curl" <<'SH'
#!/bin/bash
for state in "$LOCAL_PREVIEW_STATE_DIR"/*.json; do
  [ -f "$state" ] || continue
  python3 - "$state" "$CAPTURED_PID" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write(str(data["process_pid"]))
PY
done
exit 22
SH
  chmod +x "$fakebin/curl"

  run env PATH="$fakebin:/usr/bin:/bin" CAPTURED_PID="$captured_pid" \
    "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port"
  [ "$status" -ne 0 ]
  [[ "$output" == *"server did not verify exact local URL"* ]]
  [ -s "$captured_pid" ]
  failed_pid="$(cat "$captured_pid")"
  run kill -0 "$failed_pid"
  [ "$status" -ne 0 ]
  [ ! -e "$TEST_STATE_DIR/local-preview-$port.json" ]
  [ ! -e "$TEST_STATE_DIR/local-preview-$port.pid" ]
  [ ! -e "$TEST_STATE_DIR/local-preview-$port-run.sh" ]
}

@test "local URL success cannot mask replacement of the recorded server process" {
  port="$(free_port)"
  fakebin="$TMPDIR_TEST/replaced-process-bin"
  race_done="$TMPDIR_TEST/replaced-process.done"
  foreign_pid="$TMPDIR_TEST/replaced-process.pid"
  mkdir -p "$fakebin"
  cat > "$fakebin/curl" <<'SH'
#!/bin/bash
set -euo pipefail
if [ ! -e "$RACE_DONE" ]; then
  state="$(find "$LOCAL_PREVIEW_STATE_DIR" -maxdepth 1 -name '*.json' -print -quit)"
  owned_pid="$(/usr/bin/python3 - "$state" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["process_pid"])
PY
)"
  kill "$owned_pid"
  sleep 0.2
  nohup /usr/bin/python3 -m http.server -b 127.0.0.1 -d "$RACE_ROOT" "$RACE_PORT" \
    >/dev/null 2>&1 &
  printf '%s\n' "$!" > "$FOREIGN_PID_FILE"
  : > "$RACE_DONE"
  sleep 0.2
fi
exec /usr/bin/curl "$@"
SH
  chmod +x "$fakebin/curl"

  run env PATH="$fakebin:/usr/bin:/bin" RACE_DONE="$race_done" RACE_ROOT="$TEST_SITE" \
    RACE_PORT="$port" FOREIGN_PID_FILE="$foreign_pid" \
    "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port"

  [ "$status" -ne 0 ]
  [[ "$output" == *"spawned preview identity did not survive local URL verification"* ]]
  [ -s "$foreign_pid" ]
  UNRELATED_PID="$(cat "$foreign_pid")"
  run kill -0 "$UNRELATED_PID"
  [ "$status" -eq 0 ]
  [ ! -e "$TEST_STATE_DIR/local-preview-$port.json" ]
}

@test "wildcard LAN bind starts without a Tailscale address" {
  port="$(free_port)"
  run "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port" --lan
  [ "$status" -eq 0 ]
  [[ "$output" == *"BIND_ADDR=0.0.0.0"* ]]
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"
  run "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  PREVIEW_PID=""
}

@test "IPv6 wildcard bind completes a verified lifecycle when IPv6 is available" {
  if ! port="$(python3 - <<'PY'
import socket
sock = socket.socket(socket.AF_INET6)
try:
    sock.bind(("::1", 0))
    print(sock.getsockname()[1])
finally:
    sock.close()
PY
)"; then
    skip "IPv6 loopback unavailable"
  fi

  run "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port" --bind ::
  [ "$status" -eq 0 ]
  [[ "$output" == *"LOCAL_URL=http://[::1]:$port/"* ]]
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"
  run "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  PREVIEW_PID=""
}

@test "occupied port 65535 fails without wrapping past the TCP range" {
  /usr/bin/python3 -m http.server -b 127.0.0.1 -d "$TEST_SITE" 65535 >/dev/null 2>&1 &
  UNRELATED_PID="$!"
  sleep 0.3
  if ! kill -0 "$UNRELATED_PID" 2>/dev/null; then
    UNRELATED_PID=""
    skip "port 65535 is unavailable for the fixture"
  fi

  run "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port 65535
  [ "$status" -ne 0 ]
  [[ "$output" == *"no safely reusable TCP port"* ]]
  run kill -0 "$UNRELATED_PID"
  [ "$status" -eq 0 ]
}

@test "Tailscale off failure preserves recovery state and reports failure" {
  port="$(free_port)"
  fakebin="$TMPDIR_TEST/tailscale-bin"
  ts_state="$TMPDIR_TEST/tailscale-port"
  ts_mode="$TMPDIR_TEST/tailscale-mode"
  ts_log="$TMPDIR_TEST/tailscale.log"
  mkdir -p "$fakebin"
  write_selective_curl "$fakebin"
  write_fake_tailscale "$fakebin"

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port" --tailscale-serve
  [ "$status" -eq 0 ]
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" FAIL_OFF=1 \
    "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -ne 0 ]
  [[ "$output" == *"STOPPED=0"* ]]
  [ -f "$TEST_STATE_DIR/local-preview-$port.json" ]
  [ -f "$ts_state" ]
  run kill -0 "$PREVIEW_PID"
  [ "$status" -ne 0 ]

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" FAIL_OFF=0 \
    "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  [ ! -e "$TEST_STATE_DIR/local-preview-$port.json" ]
  [ ! -e "$ts_state" ]
  PREVIEW_PID=""
}

@test "Tailscale start rejects a successful CLI that installs a foreign mapping" {
  port="$(free_port)"
  fakebin="$TMPDIR_TEST/lying-tailscale-bin"
  ts_state="$TMPDIR_TEST/lying-tailscale-port"
  ts_mode="$TMPDIR_TEST/lying-tailscale-mode"
  ts_log="$TMPDIR_TEST/lying-tailscale.log"
  mkdir -p "$fakebin"
  write_selective_curl "$fakebin"
  write_fake_tailscale "$fakebin"

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    POST_MAPPING_MODE=foreign "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port" --tailscale-serve

  [ "$status" -ne 0 ]
  [[ "$output" == *"did not establish the exact owned mapping (foreign)"* ]]
  [ -f "$TEST_STATE_DIR/local-preview-$port.json" ]
  [ -f "$ts_state" ]
  run grep -F -- '--set-path=/ off' "$ts_log"
  [ "$status" -ne 0 ]

  printf '%s\n' owned > "$ts_mode"
  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
}

@test "stop refuses to disable a replaced foreign Tailscale mapping" {
  port="$(free_port)"
  fakebin="$TMPDIR_TEST/foreign-tailscale-bin"
  ts_state="$TMPDIR_TEST/foreign-tailscale-port"
  ts_mode="$TMPDIR_TEST/foreign-tailscale-mode"
  ts_log="$TMPDIR_TEST/foreign-tailscale.log"
  mkdir -p "$fakebin"
  write_selective_curl "$fakebin"
  write_fake_tailscale "$fakebin"

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$port" --tailscale-serve
  [ "$status" -eq 0 ]
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$port.pid")"
  printf '%s\n' foreign > "$ts_mode"
  : > "$ts_log"

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -ne 0 ]
  [ -f "$TEST_STATE_DIR/local-preview-$port.json" ]
  run grep -F -- '--set-path=/ off' "$ts_log"
  [ "$status" -ne 0 ]

  printf '%s\n' owned > "$ts_mode"
  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    "$PREVIEW_SCRIPT" stop --port "$port"
  [ "$status" -eq 0 ]
  PREVIEW_PID=""
}

@test "fallback port clears exact stale preview mapping before reuse" {
  requested="$(free_port)"
  fallback=$((requested + 1))
  [ "$fallback" -le 65535 ] || skip "no fallback port"
  python3 - "$fallback" <<'PY' || skip "fallback fixture port unavailable"
import socket
import sys
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
finally:
    sock.close()
PY
  /usr/bin/python3 -m http.server -b 127.0.0.1 -d "$TEST_SITE" "$requested" >/dev/null 2>&1 &
  UNRELATED_PID="$!"
  sleep 0.3
  kill -0 "$UNRELATED_PID" 2>/dev/null || skip "requested port fixture failed"

  fakebin="$TMPDIR_TEST/fallback-tailscale-bin"
  ts_state="$TMPDIR_TEST/fallback-tailscale-port"
  ts_mode="$TMPDIR_TEST/fallback-tailscale-mode"
  ts_log="$TMPDIR_TEST/fallback-tailscale.log"
  mkdir -p "$fakebin" "$TEST_STATE_DIR"
  write_selective_curl "$fakebin"
  write_fake_tailscale "$fakebin"
  printf '%s\n' "$fallback" > "$ts_state"
  printf '%s\n' owned > "$ts_mode"
  python3 - "$TEST_STATE_DIR/local-preview-$fallback.json" "$fallback" "$TEST_SITE" <<'PY'
import json
import sys
path, port, root = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "schema_version": 2,
        "port": int(port),
        "root": root,
        "target": root,
        "target_type": "directory",
        "url_path": "/",
        "process_mode": "pid",
        "bind_addr": "127.0.0.1",
        "tailscale_serve_enabled": True,
        "tailscale_serve_base_url": f"http://node.test.ts.net:{port}",
        "process_pid": 999999,
        "process_started_at": "dead-preview",
    }, handle)
PY

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    "$PREVIEW_SCRIPT" start --path "$TEST_SITE" --port "$requested"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PORT=$fallback"* ]]
  grep -Fq -- "--http=$fallback --set-path=/ off" "$ts_log"
  PREVIEW_PID="$(cat "$TEST_STATE_DIR/local-preview-$fallback.pid")"

  run env PATH="$fakebin:/usr/bin:/bin" TS_STATE="$ts_state" TS_MODE="$ts_mode" TS_LOG="$ts_log" \
    "$PREVIEW_SCRIPT" stop --port "$fallback"
  [ "$status" -eq 0 ]
  run kill -0 "$UNRELATED_PID"
  [ "$status" -eq 0 ]
  PREVIEW_PID=""
}
