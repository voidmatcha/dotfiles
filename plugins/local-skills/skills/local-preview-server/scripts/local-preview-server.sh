#!/usr/bin/env bash
set -euo pipefail

DEFAULT_PORT="${LOCAL_PREVIEW_DEFAULT_PORT:-8377}"
STATE_DIR="${LOCAL_PREVIEW_STATE_DIR:-/tmp}"
usage() {
  cat <<'USAGE'
Usage:
  local-preview-server.sh start --path PATH [--port PORT] [--clear-tailscale-serve-conflict]
  local-preview-server.sh status --port PORT
  local-preview-server.sh stop --port PORT

Serves a local file or static directory through a private verified browser URL.
USAGE
}

fail() {
  printf 'STATUS=error\n'
  printf 'ERROR=%s\n' "$*"
  exit 1
}

kv() {
  printf '%s=%s\n' "$1" "$2"
}

quote_value() {
  printf '%q' "$1"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

session_name() {
  printf 'local-preview-%s' "$1"
}

state_file() {
  printf '%s/local-preview-%s.env' "$STATE_DIR" "$1"
}

pid_file() {
  printf '%s/local-preview-%s.pid' "$STATE_DIR" "$1"
}

run_file() {
  printf '%s/local-preview-%s-run.sh' "$STATE_DIR" "$1"
}

log_file() {
  printf '%s/local-preview-%s.log' "$STATE_DIR" "$1"
}

url_quote_segment() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import quote
print(quote(sys.argv[1]))
PY
}

absolute_path() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve(strict=False))
PY
}

port_available() {
  python3 - "$1" <<'PY'
import socket
import sys
port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

port_accepts_local_connection() {
  python3 - "$1" <<'PY'
import socket
import sys
port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.5)
try:
    sys.exit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
finally:
    sock.close()
PY
}

find_free_port() {
  local port="$1"
  while ! port_available "$port"; do
    port=$((port + 1))
  done
  printf '%s' "$port"
}

has_tmux_session() {
  local session="$1"
  command_exists tmux && tmux has-session -t "$session" >/dev/null 2>&1
}

pid_alive() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1
}

stop_port_quiet() {
  local port="$1"
  local session pidfile pid
  session="$(session_name "$port")"
  pidfile="$(pid_file "$port")"

  if has_tmux_session "$session"; then
    tmux kill-session -t "$session" >/dev/null 2>&1 || true
  fi

  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if pid_alive "$pid"; then
      kill "$pid" >/dev/null 2>&1 || true
      local attempts=0
      while [ "$attempts" -lt 10 ]; do
        attempts=$((attempts + 1))
        pid_alive "$pid" || break
        sleep 0.2
      done
      if pid_alive "$pid"; then
        kill -KILL "$pid" >/dev/null 2>&1 || true
      fi
    fi
  fi

  rm -f "$(pid_file "$port")" "$(run_file "$port")" "$(state_file "$port")"
}

detect_lan_ip() {
  local ip iface
  if command_exists ip; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}' || true)"
    [ -n "$ip" ] && { printf '%s' "$ip"; return 0; }
  fi
  if command_exists ipconfig; then
    iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}' || true)"
    if [ -n "$iface" ]; then
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      [ -n "$ip" ] && { printf '%s' "$ip"; return 0; }
    fi
    ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
    [ -n "$ip" ] && { printf '%s' "$ip"; return 0; }
  fi
  if command_exists hostname; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    [ -n "$ip" ] && { printf '%s' "$ip"; return 0; }
  fi
  return 1
}

detect_tailnet_ip() {
  command_exists tailscale || return 1
  tailscale ip -4 2>/dev/null | head -1
}

verify_url_once() {
  local url="$1"
  command_exists curl || return 1
  curl -fsS --max-time 3 "$url" -o /dev/null >/dev/null 2>&1
}

wait_for_local_url() {
  local url="$1"
  local attempts=0
  while [ "$attempts" -lt 20 ]; do
    attempts=$((attempts + 1))
    if port_accepts_local_connection "$PORT" && verify_url_once "$url"; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

write_state() {
  local port="$1" root="$2" target="$3" target_type="$4" url_path="$5" mode="$6"
  local state
  state="$(state_file "$port")"
  {
    printf 'PORT=%s\n' "$(quote_value "$port")"
    printf 'ROOT=%s\n' "$(quote_value "$root")"
    printf 'TARGET=%s\n' "$(quote_value "$target")"
    printf 'TARGET_TYPE=%s\n' "$(quote_value "$target_type")"
    printf 'URL_PATH=%s\n' "$(quote_value "$url_path")"
    printf 'PROCESS_MODE=%s\n' "$(quote_value "$mode")"
  } > "$state"
}

load_state_if_present() {
  local port="$1"
  local state
  state="$(state_file "$port")"
  if [ -f "$state" ]; then
    # shellcheck disable=SC1090
    . "$state"
  fi
}

make_urls() {
  local port="$1" path="$2"
  LOCAL_URL="http://127.0.0.1:${port}${path}"
  LAN_IP="$(detect_lan_ip 2>/dev/null || true)"
  TAILNET_IP="$(detect_tailnet_ip 2>/dev/null || true)"
  LAN_URL=""
  TAILNET_URL=""
  if [ -n "$LAN_IP" ]; then
    LAN_URL="http://${LAN_IP}:${port}${path}"
  fi
  if [ -n "$TAILNET_IP" ]; then
    TAILNET_URL="http://${TAILNET_IP}:${port}${path}"
  fi
  return 0
}

verify_optional_url() {
  local url="$1"
  if [ -z "$url" ]; then
    printf 'unavailable'
  elif verify_url_once "$url"; then
    printf 'ok'
  else
    printf 'failed'
  fi
}

emit_common() {
  local status="$1" port="$2" root="$3" target="$4" target_type="$5" url_path="$6" mode="$7"
  local session log stop_command listener_verify local_verify lan_verify tailnet_verify preferred_url
  session="$(session_name "$port")"
  log="$(log_file "$port")"
  make_urls "$port" "$url_path"

  if port_accepts_local_connection "$port"; then
    listener_verify="ok"
  else
    listener_verify="failed"
  fi
  local_verify="$(verify_optional_url "$LOCAL_URL")"
  lan_verify="$(verify_optional_url "$LAN_URL")"
  tailnet_verify="$(verify_optional_url "$TAILNET_URL")"

  preferred_url="$LOCAL_URL"
  if [ "$tailnet_verify" = "ok" ]; then
    preferred_url="$TAILNET_URL"
  elif [ "$lan_verify" = "ok" ]; then
    preferred_url="$LAN_URL"
  fi

  if [ "$mode" = "tmux" ]; then
    stop_command="tmux kill-session -t ${session}"
  else
    stop_command="$(basename "$0") stop --port ${port}"
  fi

  kv STATUS "$status"
  kv PREFERRED_URL "$preferred_url"
  kv LOCAL_URL "$LOCAL_URL"
  kv LAN_URL "$LAN_URL"
  kv TAILNET_URL "$TAILNET_URL"
  kv ROOT "$root"
  kv TARGET "$target"
  kv TARGET_TYPE "$target_type"
  kv PORT "$port"
  kv SESSION "$session"
  kv PROCESS_MODE "$mode"
  kv LOG "$log"
  kv STOP_COMMAND "$stop_command"
  kv LISTENER_VERIFY "$listener_verify"
  kv LOCAL_VERIFY "$local_verify"
  kv LAN_VERIFY "$lan_verify"
  kv TAILNET_VERIFY "$tailnet_verify"
}

start_server() {
  local target_path="" requested_port="" clear_tailscale_conflict="0"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --path)
        [ "$#" -ge 2 ] || fail "--path requires a value"
        target_path="$2"
        shift 2
        ;;
      --port)
        [ "$#" -ge 2 ] || fail "--port requires a value"
        requested_port="$2"
        shift 2
        ;;
      --clear-tailscale-serve-conflict)
        clear_tailscale_conflict="1"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "unknown start option: $1"
        ;;
    esac
  done

  [ -n "$target_path" ] || fail "start requires --path"
  command_exists python3 || fail "python3 is required"
  command_exists curl || fail "curl is required for verification"

  local target root target_type url_path port session log run mode encoded_name port_note
  target="$(absolute_path "$target_path")"
  [ -e "$target" ] || fail "path does not exist: $target"
  if [ -f "$target" ]; then
    target_type="file"
    root="$(dirname "$target")"
    encoded_name="$(url_quote_segment "$(basename "$target")")"
    url_path="/${encoded_name}"
  elif [ -d "$target" ]; then
    target_type="directory"
    root="$target"
    url_path="/"
  else
    fail "path is neither a regular file nor a directory: $target"
  fi

  requested_port="${requested_port:-$DEFAULT_PORT}"
  [[ "$requested_port" =~ ^[0-9]+$ ]] || fail "port must be numeric: $requested_port"
  [ "$requested_port" -ge 1 ] && [ "$requested_port" -le 65535 ] || fail "port out of range: $requested_port"

  stop_port_quiet "$requested_port" || true
  port="$requested_port"
  port_note="requested"
  if ! port_available "$port"; then
    port="$(find_free_port "$((requested_port + 1))")"
    port_note="requested_port_occupied_used_next_free"
  fi

  session="$(session_name "$port")"
  log="$(log_file "$port")"
  run="$(run_file "$port")"
  : > "$log"
  cat > "$run" <<RUNNER
#!/usr/bin/env bash
set -euo pipefail
ROOT=$(quote_value "$root")
PORT=$(quote_value "$port")
LOG=$(quote_value "$log")
printf '[local-preview] serving %s on 0.0.0.0:%s\n' "\$ROOT" "\$PORT" >>"\$LOG"
exec python3 -m http.server -b 0.0.0.0 -d "\$ROOT" "\$PORT" >>"\$LOG" 2>&1
RUNNER
  chmod +x "$run"

  if command_exists tmux; then
    tmux new-session -d -s "$session" "$run"
    mode="tmux"
  else
    nohup "$run" >/dev/null 2>&1 &
    printf '%s\n' "$!" > "$(pid_file "$port")"
    mode="pid"
  fi

  PORT="$port"
  make_urls "$port" "$url_path"
  if ! wait_for_local_url "$LOCAL_URL"; then
    printf 'STATUS=error\n'
    kv ERROR "server did not verify exact local URL"
    kv LOCAL_URL "$LOCAL_URL"
    kv PORT "$port"
    kv SESSION "$session"
    kv LOG "$log"
    exit 1
  fi

  if [ "$clear_tailscale_conflict" = "1" ] && [ -n "${TAILNET_URL:-}" ] && ! verify_url_once "$TAILNET_URL" && command_exists tailscale; then
    tailscale serve --http="$port" off >/dev/null 2>&1 || true
  fi

  write_state "$port" "$root" "$target" "$target_type" "$url_path" "$mode"
  emit_common ok "$port" "$root" "$target" "$target_type" "$url_path" "$mode"
  kv REQUESTED_PORT "$requested_port"
  kv PORT_NOTE "$port_note"
}

status_server() {
  local port=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --port)
        [ "$#" -ge 2 ] || fail "--port requires a value"
        port="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "unknown status option: $1"
        ;;
    esac
  done
  [ -n "$port" ] || fail "status requires --port"
  [[ "$port" =~ ^[0-9]+$ ]] || fail "port must be numeric: $port"

  local session mode root target target_type url_path status pid
  session="$(session_name "$port")"
  ROOT=""
  TARGET=""
  TARGET_TYPE="unknown"
  URL_PATH="/"
  PROCESS_MODE="unknown"
  load_state_if_present "$port"
  root="${ROOT:-}"
  target="${TARGET:-}"
  target_type="${TARGET_TYPE:-unknown}"
  url_path="${URL_PATH:-/}"
  mode="${PROCESS_MODE:-unknown}"

  status="stopped"
  if has_tmux_session "$session"; then
    status="ok"
    mode="tmux"
  elif [ -f "$(pid_file "$port")" ]; then
    pid="$(cat "$(pid_file "$port")" 2>/dev/null || true)"
    if pid_alive "$pid"; then
      status="ok"
      mode="pid"
    fi
  fi
  if [ "$status" = "ok" ] && ! port_accepts_local_connection "$port"; then
    status="degraded"
  fi
  emit_common "$status" "$port" "$root" "$target" "$target_type" "$url_path" "$mode"
}

stop_server() {
  local port=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --port)
        [ "$#" -ge 2 ] || fail "--port requires a value"
        port="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "unknown stop option: $1"
        ;;
    esac
  done
  [ -n "$port" ] || fail "stop requires --port"
  [[ "$port" =~ ^[0-9]+$ ]] || fail "port must be numeric: $port"

  local session log
  session="$(session_name "$port")"
  log="$(log_file "$port")"
  stop_port_quiet "$port" || true
  kv STATUS ok
  kv STOPPED 1
  kv PORT "$port"
  kv SESSION "$session"
  kv LOG "$log"
}

main() {
  [ "$#" -gt 0 ] || { usage; exit 2; }
  local command="$1"
  shift
  case "$command" in
    start) start_server "$@" ;;
    status) status_server "$@" ;;
    stop) stop_server "$@" ;;
    -h|--help) usage ;;
    *) fail "unknown command: $command" ;;
  esac
}

main "$@"
