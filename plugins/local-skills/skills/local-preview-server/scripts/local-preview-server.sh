#!/usr/bin/env bash
set -euo pipefail
umask 077

DEFAULT_PORT="${LOCAL_PREVIEW_DEFAULT_PORT:-8377}"
DEFAULT_BIND_ADDR="${LOCAL_PREVIEW_BIND_ADDR:-127.0.0.1}"
STATE_SCHEMA_VERSION="2"
if [ -n "${LOCAL_PREVIEW_STATE_DIR:-}" ]; then
  STATE_DIR="$LOCAL_PREVIEW_STATE_DIR"
elif [ -n "${XDG_STATE_HOME:-}" ]; then
  STATE_DIR="${XDG_STATE_HOME}/local-preview-server"
elif [ -n "${HOME:-}" ]; then
  STATE_DIR="${HOME}/.local/state/local-preview-server"
else
  STATE_DIR=""
fi

usage() {
  cat <<'USAGE'
Usage:
  local-preview-server.sh start --path PATH [--port PORT] [--tailscale-serve] [--bind ADDR|--lan] [--clear-tailscale-serve-conflict]
  local-preview-server.sh status --port PORT
  local-preview-server.sh stop --port PORT

Serves a local file or static directory through a verified private browser URL.
Default exposure is localhost-only. Use --tailscale-serve for tailnet access;
use --lan/--bind 0.0.0.0 only when LAN exposure is explicitly intended.
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

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

ensure_state_dir() {
  [ -n "$STATE_DIR" ] || fail "HOME, XDG_STATE_HOME, or LOCAL_PREVIEW_STATE_DIR is required"
  if [ -L "$STATE_DIR" ]; then
    fail "state directory must not be a symlink: $STATE_DIR"
  fi
  if [ -e "$STATE_DIR" ] && [ ! -d "$STATE_DIR" ]; then
    fail "state path is not a directory: $STATE_DIR"
  fi
  mkdir -p "$STATE_DIR" || fail "could not create state directory: $STATE_DIR"
  if [ -L "$STATE_DIR" ] || [ ! -O "$STATE_DIR" ]; then
    fail "state directory must be owned by the current user and not be a symlink: $STATE_DIR"
  fi
  chmod 700 "$STATE_DIR" || fail "could not secure state directory: $STATE_DIR"
}

session_name() {
  printf 'local-preview-%s' "$1"
}

state_file() {
  printf '%s/local-preview-%s.json' "$STATE_DIR" "$1"
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

file_root() {
  printf '%s/local-preview-%s-root' "$STATE_DIR" "$1"
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

resolve_script_path() {
  local candidate="$0"
  case "$candidate" in
    */*) ;;
    *) candidate="$(command -v "$candidate")" || return 1 ;;
  esac
  absolute_path "$candidate"
}

SCRIPT_PATH="$(resolve_script_path)" || fail "could not resolve the preview helper path"

port_available() {
  local port="$1" bind_addr="${2:-$DEFAULT_BIND_ADDR}"
  python3 - "$port" "$bind_addr" <<'PY'
import socket
import sys
port = int(sys.argv[1])
bind_addr = sys.argv[2]
try:
    addresses = socket.getaddrinfo(bind_addr, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
except socket.gaierror:
    raise SystemExit(1)
for family, socktype, proto, _, sockaddr in addresses:
    sock = socket.socket(family, socktype, proto)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(sockaddr)
    except OSError:
        continue
    finally:
        sock.close()
    raise SystemExit(0)
raise SystemExit(1)
PY
}

bind_addr_valid() {
  python3 - "$1" <<'PY'
import socket
import sys
try:
    addresses = socket.getaddrinfo(sys.argv[1], 0, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
except socket.gaierror:
    raise SystemExit(1)
raise SystemExit(0 if addresses else 1)
PY
}

local_probe_host() {
  case "$1" in
    0.0.0.0) printf '127.0.0.1' ;;
    ::) printf '::1' ;;
    *) printf '%s' "$1" ;;
  esac
}

url_host() {
  case "$1" in
    *:*) printf '[%s]' "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}

port_accepts_local_connection() {
  local port="$1" bind_addr="${2:-$DEFAULT_BIND_ADDR}" host
  host="$(local_probe_host "$bind_addr")"
  python3 - "$port" "$host" <<'PY'
import socket
import sys
port = int(sys.argv[1])
host = sys.argv[2]
try:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
except socket.gaierror:
    raise SystemExit(1)
for family, socktype, proto, _, sockaddr in addresses:
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(0.5)
    try:
        if sock.connect_ex(sockaddr) == 0:
            raise SystemExit(0)
    finally:
        sock.close()
raise SystemExit(1)
PY
}

has_tmux_session() {
  local session="$1"
  command_exists tmux && tmux has-session -t "$session" >/dev/null 2>&1
}

load_state_if_present() {
  local port="$1" state key encoded value state_loaded="0" parsed
  state="$(state_file "$port")"
  [ -e "$state" ] || [ -L "$state" ] || return 1
  [ ! -L "$state" ] && [ -f "$state" ] && [ -O "$state" ] || return 1

  parsed="$(mktemp "${STATE_DIR}/.state-read.XXXXXX")" || return 1
  if ! python3 - "$state" "$port" > "$parsed" <<'PY'
import base64
import json
import os
import stat
import sys

path, expected_port_text = sys.argv[1:]
required = {
    "schema_version",
    "port",
    "root",
    "target",
    "target_type",
    "url_path",
    "process_mode",
    "bind_addr",
    "tailscale_serve_enabled",
    "tailscale_serve_base_url",
    "process_pid",
    "process_started_at",
}

try:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError("state is not a user-owned regular file")
    with os.fdopen(fd, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("state keys do not match the schema")
    if data["schema_version"] != 2:
        raise ValueError("unsupported state schema")
    if isinstance(data["port"], bool) or not isinstance(data["port"], int):
        raise ValueError("state port is not an integer")
    if data["port"] != int(expected_port_text) or not 1 <= data["port"] <= 65535:
        raise ValueError("state port does not match")
    for key in (
        "root",
        "target",
        "target_type",
        "url_path",
        "process_mode",
        "bind_addr",
        "tailscale_serve_base_url",
    ):
        if not isinstance(data[key], str) or "\0" in data[key]:
            raise ValueError(f"state {key} is not a safe string")
    if data["target_type"] not in {"file", "directory"}:
        raise ValueError("invalid target type")
    if data["process_mode"] not in {"tmux", "pid"}:
        raise ValueError("invalid process mode")
    if not data["url_path"].startswith("/") or not data["bind_addr"]:
        raise ValueError("invalid URL path or bind address")
    if not isinstance(data["tailscale_serve_enabled"], bool):
        raise ValueError("tailscale flag is not boolean")
    if isinstance(data["process_pid"], bool) or not isinstance(data["process_pid"], int) or data["process_pid"] < 0:
        raise ValueError("process pid is invalid")
    if not isinstance(data["process_started_at"], str):
        raise ValueError("process start signature is invalid")
    if data["process_mode"] == "pid" and (data["process_pid"] <= 0 or not data["process_started_at"]):
        raise ValueError("pid mode requires process identity")
    if data["process_mode"] == "tmux" and (data["process_pid"] != 0 or not data["process_started_at"]):
        raise ValueError("tmux mode requires a session identity and no pid")
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)

values = {
    "ROOT": data["root"],
    "TARGET": data["target"],
    "TARGET_TYPE": data["target_type"],
    "URL_PATH": data["url_path"],
    "PROCESS_MODE": data["process_mode"],
    "BIND_ADDR": data["bind_addr"],
    "TAILSCALE_SERVE_ENABLED": "1" if data["tailscale_serve_enabled"] else "0",
    "TAILSCALE_SERVE_BASE_URL": data["tailscale_serve_base_url"],
    "STATE_PROCESS_PID": str(data["process_pid"]),
    "STATE_PROCESS_STARTED_AT": data["process_started_at"],
    "__VALID__": "1",
}
for key, value in values.items():
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    print(f"{key}\t{encoded}")
PY
  then
    rm -f "$parsed"
    return 1
  fi

  while IFS=$'\t' read -r key encoded; do
    value="$(python3 -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.argv[1], validate=True))' "$encoded")" || {
      rm -f "$parsed"
      return 1
    }
    case "$key" in
      ROOT) ROOT="$value" ;;
      TARGET) TARGET="$value" ;;
      TARGET_TYPE) TARGET_TYPE="$value" ;;
      URL_PATH) URL_PATH="$value" ;;
      PROCESS_MODE) PROCESS_MODE="$value" ;;
      BIND_ADDR) BIND_ADDR="$value" ;;
      TAILSCALE_SERVE_ENABLED) TAILSCALE_SERVE_ENABLED="$value" ;;
      TAILSCALE_SERVE_BASE_URL) TAILSCALE_SERVE_BASE_URL="$value" ;;
      STATE_PROCESS_PID) STATE_PROCESS_PID="$value" ;;
      STATE_PROCESS_STARTED_AT) STATE_PROCESS_STARTED_AT="$value" ;;
      __VALID__) state_loaded="1" ;;
      *)
        rm -f "$parsed"
        return 1
        ;;
    esac
  done < "$parsed"
  rm -f "$parsed"
  [ "$state_loaded" = "1" ]
}

pid_matches_server() {
  local pid="$1" port="$2" root="$3" bind_addr="$4" expected_pid="$5" expected_started_at="$6"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  python3 - "$pid" "$port" "$root" "$bind_addr" "$expected_pid" "$expected_started_at" <<'PY'
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

pid, expected_port, expected_root, expected_bind_addr, expected_pid, expected_started_at = sys.argv[1:]
if not re.fullmatch(r"[1-9][0-9]*", pid):
    raise SystemExit(1)
if pid != expected_pid or not expected_started_at:
    raise SystemExit(1)
try:
    uid = subprocess.check_output(["ps", "-p", pid, "-o", "uid="], text=True).strip()
    command = subprocess.check_output(["ps", "-p", pid, "-o", "command="], text=True).strip()
    started_at = subprocess.check_output(["ps", "-p", pid, "-o", "lstart="], text=True).strip()
    parts = shlex.split(command)
except (OSError, subprocess.CalledProcessError, ValueError):
    raise SystemExit(1)
if uid != str(os.geteuid()) or started_at != expected_started_at or not parts:
    raise SystemExit(1)
if not re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?", Path(parts[0]).name, flags=re.IGNORECASE):
    raise SystemExit(1)
expected_args = [
    "-m",
    "http.server",
    "-b",
    expected_bind_addr,
    "-d",
    expected_root,
    expected_port,
]
if parts[1:] != expected_args:
    raise SystemExit(1)
PY
}

process_start_signature() {
  local pid="$1"
  ps -p "$pid" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

tmux_session_identity() {
  local session="$1"
  tmux display-message -p -t "$session" '#{session_created}:#{pane_pid}' 2>/dev/null
}

tmux_session_matches() {
  local session="$1" expected_identity="$2" actual_identity
  [ -n "$expected_identity" ] || return 1
  actual_identity="$(tmux_session_identity "$session")"
  [ -n "$actual_identity" ] && [ "$actual_identity" = "$expected_identity" ]
}

recorded_process_matches() {
  local port="$1" mode="$2" session="$3" root="$4" bind_addr="$5" process_pid="$6" process_started_at="$7"
  if [ "$mode" = "tmux" ]; then
    command_exists tmux && has_tmux_session "$session" && \
      tmux_session_matches "$session" "$process_started_at"
  else
    pid_matches_server "$process_pid" "$port" "$root" "$bind_addr" \
      "$process_pid" "$process_started_at"
  fi
}

atomic_write_stdin() {
  local destination="$1" mode="$2" tmp
  [ ! -L "$destination" ] || return 1
  tmp="$(mktemp "${destination}.tmp.XXXXXX")" || return 1
  if ! cat > "$tmp" || ! chmod "$mode" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  if [ -L "$destination" ]; then
    rm -f "$tmp"
    return 1
  fi
  mv -f "$tmp" "$destination"
}

tailscale_mapping_status() {
  local port="$1" status_json serve_json
  command_exists tailscale || { printf 'unverifiable'; return 0; }
  status_json="$(mktemp "${STATE_DIR}/.tailscale-status.XXXXXX")" || { printf 'unverifiable'; return 0; }
  serve_json="$(mktemp "${STATE_DIR}/.tailscale-serve.XXXXXX")" || {
    rm -f "$status_json"
    printf 'unverifiable'
    return 0
  }
  if ! tailscale status --json >"$status_json" 2>/dev/null || \
      ! tailscale serve status --json >"$serve_json" 2>/dev/null; then
    rm -f "$status_json" "$serve_json"
    printf 'unverifiable'
    return 0
  fi
  python3 - "$port" "$status_json" "$serve_json" <<'PY'
import json
import sys

port, status_path, serve_path = sys.argv[1:]
try:
    with open(status_path, encoding="utf-8") as handle:
        status = json.load(handle)
    with open(serve_path, encoding="utf-8") as handle:
        serve = json.load(handle)
    if not isinstance(status, dict) or not isinstance(serve, dict):
        raise ValueError
    tcp = serve.get("TCP", {})
    web = serve.get("Web", {})
    funnel = serve.get("AllowFunnel", {})
    if not isinstance(tcp, dict) or not isinstance(web, dict) or not isinstance(funnel, dict):
        raise ValueError
    same_port_web = sorted(
        key for key in web if isinstance(key, str) and key.rsplit(":", 1)[-1] == port
    )
    same_port_funnel = sorted(
        key for key in funnel if isinstance(key, str) and key.rsplit(":", 1)[-1] == port
    )
    if port not in tcp and not same_port_web and not same_port_funnel:
        print("absent")
        raise SystemExit(0)
    self_data = status.get("Self")
    if not isinstance(self_data, dict):
        raise ValueError
    host = self_data.get("DNSName")
    if not isinstance(host, str) or not host.strip().rstrip("."):
        raise ValueError
    host_port = f"{host.strip().rstrip('.')}:{port}"
    backend = f"http://127.0.0.1:{port}"
    expected_web = {"Handlers": {"/": {"Proxy": backend}}}
    owned = (
        tcp.get(port) == {"HTTP": True}
        and same_port_web == [host_port]
        and web.get(host_port) == expected_web
        and not same_port_funnel
    )
    print("owned" if owned else "foreign")
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    print("unverifiable")
PY
  rm -f "$status_json" "$serve_json"
}

clear_owned_tailscale_serve_for_port() {
  local port="$1" mapping post_mapping
  mapping="$(tailscale_mapping_status "$port")"
  case "$mapping" in
    absent) return 0 ;;
    owned)
      if ! tailscale serve --bg --http="$port" --set-path=/ off >/dev/null 2>&1; then
        return 1
      fi
      post_mapping="$(tailscale_mapping_status "$port")"
      [ "$post_mapping" = "absent" ]
      ;;
    *) return 1 ;;
  esac
}

cleanup_private_file_root() {
  local port="$1" root="$2" expected
  expected="$(file_root "$port")"
  [ "$root" = "$expected" ] || return 1
  if [ -L "$root" ]; then
    return 1
  fi
  [ ! -e "$root" ] || [ -O "$root" ] || return 1
  rm -rf "$root"
}

prepare_private_file_root() {
  local port="$1" source="$2" name="$3" root
  root="$(file_root "$port")"
  [ ! -e "$root" ] && [ ! -L "$root" ] || return 1
  python3 - "$root" "$source" "$name" <<'PY'
import os
import shutil
import stat
import sys
import tempfile

root, source, name = sys.argv[1:]
if not name or name in {".", ".."} or "/" in name or "\0" in name:
    raise SystemExit(1)
os.mkdir(root, 0o700)
temporary = ""
try:
    info = os.stat(root, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise OSError("untrusted serving root")
    fd, temporary = tempfile.mkstemp(prefix=".preview-file.", dir=root)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as destination, open(source, "rb") as source_file:
        shutil.copyfileobj(source_file, destination)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, os.path.join(root, name))
except Exception:
    if temporary:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    shutil.rmtree(root, ignore_errors=True)
    raise
PY
  printf '%s' "$root"
}

stop_port_quiet() {
  local port="$1" session pidfile pid state_had_tailscale="0" state_loaded="0" state
  local attempts=0
  STOP_ERROR=""
  STOPPED_RESULT="0"
  session="$(session_name "$port")"
  pidfile="$(pid_file "$port")"
  state="$(state_file "$port")"

  ROOT=""
  TARGET=""
  TARGET_TYPE="unknown"
  URL_PATH="/"
  PROCESS_MODE="unknown"
  BIND_ADDR="$DEFAULT_BIND_ADDR"
  TAILSCALE_SERVE_ENABLED="0"
  TAILSCALE_SERVE_BASE_URL=""
  STATE_PROCESS_PID="0"
  STATE_PROCESS_STARTED_AT=""
  if load_state_if_present "$port"; then
    state_loaded="1"
  elif [ -e "$state" ] || [ -L "$state" ]; then
    STOP_ERROR="recorded preview state is invalid or untrusted; evidence was preserved"
    return 1
  fi
  state_had_tailscale="${TAILSCALE_SERVE_ENABLED:-0}"

  if [ "$state_loaded" = "0" ]; then
    if [ -e "$pidfile" ] || [ -L "$pidfile" ] || has_tmux_session "$session"; then
      STOP_ERROR="process evidence exists without trusted preview state; evidence was preserved"
      return 1
    fi
    rm -f "$(run_file "$port")"
    return 0
  fi

  if [ "$PROCESS_MODE" = "tmux" ]; then
    if ! command_exists tmux; then
      STOP_ERROR="tmux preview ownership cannot be verified because tmux is unavailable"
      return 1
    fi
    if has_tmux_session "$session"; then
      if ! tmux_session_matches "$session" "$STATE_PROCESS_STARTED_AT"; then
        STOP_ERROR="tmux session identity no longer matches recorded preview state"
        return 1
      fi
      if ! tmux kill-session -t "$session" >/dev/null 2>&1 || has_tmux_session "$session"; then
        STOP_ERROR="owned tmux preview could not be stopped"
        return 1
      fi
    fi
  else
    pid="$STATE_PROCESS_PID"
    if kill -0 "$pid" 2>/dev/null; then
      if ! pid_matches_server "$pid" "$port" "$ROOT" "$BIND_ADDR" \
          "$STATE_PROCESS_PID" "$STATE_PROCESS_STARTED_AT"; then
        STOP_ERROR="live PID identity no longer matches recorded preview state"
        return 1
      fi
      if ! kill "$pid" >/dev/null 2>&1; then
        STOP_ERROR="owned preview process could not be signaled"
        return 1
      fi
      while [ "$attempts" -lt 10 ]; do
        attempts=$((attempts + 1))
        pid_matches_server "$pid" "$port" "$ROOT" "$BIND_ADDR" \
          "$STATE_PROCESS_PID" "$STATE_PROCESS_STARTED_AT" || break
        sleep 0.2
      done
      if pid_matches_server "$pid" "$port" "$ROOT" "$BIND_ADDR" \
          "$STATE_PROCESS_PID" "$STATE_PROCESS_STARTED_AT"; then
        kill -KILL "$pid" >/dev/null 2>&1 || true
        sleep 0.1
      fi
      if pid_matches_server "$pid" "$port" "$ROOT" "$BIND_ADDR" \
          "$STATE_PROCESS_PID" "$STATE_PROCESS_STARTED_AT"; then
        STOP_ERROR="owned preview process remained alive after termination"
        return 1
      fi
    fi
  fi

  if [ "$state_had_tailscale" = "1" ] && ! clear_owned_tailscale_serve_for_port "$port"; then
    STOP_ERROR="tailscale serve mapping is foreign, unverifiable, or could not be removed"
    return 1
  fi

  if [ "$TARGET_TYPE" = "file" ] && ! cleanup_private_file_root "$port" "$ROOT"; then
    STOP_ERROR="private single-file serving root could not be verified or removed"
    return 1
  fi
  rm -f "$pidfile" "$(run_file "$port")" "$state"
  STOPPED_RESULT="1"
  return 0
}

detect_lan_ip() {
  local ip iface
  if command_exists ip; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}' || true)"
    if [ -n "$ip" ]; then
      printf '%s' "$ip"
      return 0
    fi
  fi

  if command_exists ipconfig; then
    iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}' || true)"
    if [ -n "$iface" ]; then
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      if [ -n "$ip" ]; then
        printf '%s' "$ip"
        return 0
      fi
    fi
    ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
    if [ -n "$ip" ]; then
      printf '%s' "$ip"
      return 0
    fi
  fi

  if command_exists hostname; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    if [ -n "$ip" ]; then
      printf '%s' "$ip"
      return 0
    fi
  fi
  return 1
}

detect_tailnet_ip() {
  command_exists tailscale || return 1
  tailscale ip -4 2>/dev/null | head -1
}

detect_tailnet_host() {
  command_exists tailscale || return 1
  local host
  host="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; data=json.load(sys.stdin); print(((data.get("Self") or {}).get("DNSName") or "").strip().rstrip("."))' 2>/dev/null || true)"
  if [ -n "$host" ]; then
    printf '%s' "$host"
    return 0
  fi
  detect_tailnet_ip
}

verify_url_once() {
  local url="$1"
  curl -fsS --noproxy '*' --max-time 3 "$url" -o /dev/null >/dev/null 2>&1
}

wait_for_local_url() {
  local port="$1" url="$2" bind_addr="${3:-$DEFAULT_BIND_ADDR}"
  local attempts=0
  while [ "$attempts" -lt 20 ]; do
    attempts=$((attempts + 1))
    if port_accepts_local_connection "$port" "$bind_addr" && verify_url_once "$url"; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

write_state() {
  local port="$1" root="$2" target="$3" target_type="$4" url_path="$5" mode="$6" bind_addr="$7" tailscale_enabled="$8" tailscale_base_url="$9"
  local process_pid="${10:-0}" process_started_at="${11:-}"
  local state
  state="$(state_file "$port")"
  python3 - "$state" "$STATE_SCHEMA_VERSION" "$port" "$root" "$target" "$target_type" "$url_path" "$mode" "$bind_addr" "$tailscale_enabled" "$tailscale_base_url" "$process_pid" "$process_started_at" <<'PY'
import json
import os
import stat
import sys
import tempfile

(
    path,
    schema_version,
    port,
    root,
    target,
    target_type,
    url_path,
    process_mode,
    bind_addr,
    tailscale_enabled,
    tailscale_base_url,
    process_pid,
    process_started_at,
) = sys.argv[1:]

try:
    existing = os.lstat(path)
except FileNotFoundError:
    existing = None
if existing is not None and stat.S_ISLNK(existing.st_mode):
    raise SystemExit("refusing to replace symlinked state file")

payload = {
    "schema_version": int(schema_version),
    "port": int(port),
    "root": root,
    "target": target,
    "target_type": target_type,
    "url_path": url_path,
    "process_mode": process_mode,
    "bind_addr": bind_addr,
    "tailscale_serve_enabled": tailscale_enabled == "1",
    "tailscale_serve_base_url": tailscale_base_url,
    "process_pid": int(process_pid),
    "process_started_at": process_started_at,
}
fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.tmp.", dir=os.path.dirname(path))
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

make_urls() {
  local port="$1" path="$2" bind_addr="${3:-$DEFAULT_BIND_ADDR}" tailscale_base_url="${4:-}"
  local probe_host
  probe_host="$(local_probe_host "$bind_addr")"
  LOCAL_URL="http://$(url_host "$probe_host"):${port}${path}"
  LAN_IP=""
  TAILNET_IP=""
  LAN_URL=""
  TAILNET_URL=""

  if [ -n "$tailscale_base_url" ]; then
    TAILNET_URL="${tailscale_base_url%/}${path}"
    return 0
  fi

  if [ "$bind_addr" = "0.0.0.0" ] || [ "$bind_addr" = "::" ]; then
    LAN_IP="$(detect_lan_ip 2>/dev/null || true)"
    TAILNET_IP="$(detect_tailnet_ip 2>/dev/null || true)"
    [ -n "$LAN_IP" ] && LAN_URL="http://${LAN_IP}:${port}${path}"
    [ -n "$TAILNET_IP" ] && TAILNET_URL="http://${TAILNET_IP}:${port}${path}"
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
  local session log stop_command listener_verify local_verify lan_verify tailnet_verify preferred_url bind_addr tailscale_base_url
  session="$(session_name "$port")"
  log="$(log_file "$port")"
  bind_addr="${BIND_ADDR:-$DEFAULT_BIND_ADDR}"
  tailscale_base_url="${TAILSCALE_SERVE_BASE_URL:-}"
  make_urls "$port" "$url_path" "$bind_addr" "$tailscale_base_url"

  if port_accepts_local_connection "$port" "$bind_addr"; then
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

  # Always route users through the helper so stop_port_quiet can prove the
  # recorded process/session identity before terminating anything. Exposing a
  # raw tmux command would let a later same-name session bypass that check.
  printf -v stop_command '%q stop --port %q' "$SCRIPT_PATH" "$port"

  kv STATUS "$status"
  kv PREFERRED_URL "$preferred_url"
  kv LOCAL_URL "$LOCAL_URL"
  kv LAN_URL "$LAN_URL"
  kv TAILNET_URL "$TAILNET_URL"
  kv ROOT "$root"
  kv TARGET "$target"
  kv TARGET_TYPE "$target_type"
  kv PORT "$port"
  kv BIND_ADDR "$bind_addr"
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
  local target_path="" requested_port="" clear_tailscale_conflict="0" bind_addr="$DEFAULT_BIND_ADDR" tailscale_serve="${LOCAL_PREVIEW_TAILSCALE_SERVE:-0}"
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
      --bind)
        [ "$#" -ge 2 ] || fail "--bind requires a value"
        bind_addr="$2"
        shift 2
        ;;
      --lan)
        bind_addr="0.0.0.0"
        shift
        ;;
      --tailscale-serve)
        tailscale_serve="1"
        shift
        ;;
      --no-tailscale-serve)
        tailscale_serve="0"
        shift
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
  [ -n "$bind_addr" ] || fail "bind address must not be empty"
  command_exists python3 || fail "python3 is required"
  command_exists curl || fail "curl is required for verification"
  bind_addr_valid "$bind_addr" || fail "bind address is invalid or unavailable: $bind_addr"

  local target root target_type url_path port session log run mode encoded_name port_note tailscale_enabled tailscale_base_url tailnet_host spawned_pid="" spawned_started_at=""
  local candidate mapping_status
  tailscale_enabled="0"
  tailscale_base_url=""
  target="$(absolute_path "$target_path")"
  [ -e "$target" ] || fail "path does not exist: $target"

  if [ -f "$target" ]; then
    target_type="file"
    root=""
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

  if ! stop_port_quiet "$requested_port"; then
    fail "cannot safely clean requested preview port $requested_port: $STOP_ERROR"
  fi
  port=""
  candidate="$requested_port"
  while [ "$candidate" -le 65535 ]; do
    if port_available "$candidate" "$bind_addr"; then
      if [ "$candidate" != "$requested_port" ]; then
        # A network-free fallback can still have stale preview/Tailscale state.
        # Clean it only with recorded ownership proof, then recheck the port.
        if ! stop_port_quiet "$candidate" || ! port_available "$candidate" "$bind_addr"; then
          candidate=$((candidate + 1))
          continue
        fi
      fi
      port="$candidate"
      break
    fi
    candidate=$((candidate + 1))
  done
  [ -n "$port" ] || fail "no safely reusable TCP port is available at or above $requested_port"
  port_note="requested"
  [ "$port" = "$requested_port" ] || port_note="requested_port_occupied_used_next_free"

  if [ "$target_type" = "file" ]; then
    if ! root="$(prepare_private_file_root "$port" "$target" "$(basename "$target")")"; then
      fail "could not create an isolated single-file serving root"
    fi
  fi

  session="$(session_name "$port")"
  log="$(log_file "$port")"
  run="$(run_file "$port")"
  if ! atomic_write_stdin "$run" 700 <<RUNNER
#!/usr/bin/env bash
set -euo pipefail
ROOT=$(printf '%q' "$root")
PORT=$(printf '%q' "$port")
BIND_ADDR=$(printf '%q' "$bind_addr")
LOG=$(printf '%q' "$log")
printf '[local-preview] serving %s on %s:%s\n' "\$ROOT" "\$BIND_ADDR" "\$PORT" >>"\$LOG"
exec python3 -m http.server -b "\$BIND_ADDR" -d "\$ROOT" "\$PORT" >>"\$LOG" 2>&1
RUNNER
  then
    [ "$target_type" != "file" ] || cleanup_private_file_root "$port" "$root" || true
    fail "could not write secure runner file"
  fi

  if command_exists tmux; then
    if ! tmux new-session -d -s "$session" "$run"; then
      rm -f "$run"
      [ "$target_type" != "file" ] || cleanup_private_file_root "$port" "$root" || true
      fail "could not start preview tmux session"
    fi
    mode="tmux"
    spawned_started_at="$(tmux_session_identity "$session")"
    if [ -z "$spawned_started_at" ]; then
      tmux kill-session -t "$session" >/dev/null 2>&1 || true
      rm -f "$run"
      [ "$target_type" != "file" ] || cleanup_private_file_root "$port" "$root" || true
      fail "could not record preview tmux session identity"
    fi
  else
    nohup "$run" >/dev/null 2>&1 &
    spawned_pid="$!"
    if ! printf '%s\n' "$spawned_pid" | atomic_write_stdin "$(pid_file "$port")" 600; then
      kill "$spawned_pid" >/dev/null 2>&1 || true
      rm -f "$run"
      [ "$target_type" != "file" ] || cleanup_private_file_root "$port" "$root" || true
      fail "could not write secure pid file"
    fi
    spawned_started_at="$(process_start_signature "$spawned_pid")"
    if [ -z "$spawned_started_at" ]; then
      kill "$spawned_pid" >/dev/null 2>&1 || true
      rm -f "$(pid_file "$port")" "$run"
      [ "$target_type" != "file" ] || cleanup_private_file_root "$port" "$root" || true
      fail "could not record preview process identity"
    fi
    mode="pid"
  fi

  # Persist the exact root/bind/process identity before network verification so
  # every later cleanup path can prove it owns the process it is about to stop.
  if ! write_state "$port" "$root" "$target" "$target_type" "$url_path" "$mode" "$bind_addr" "0" "" \
      "${spawned_pid:-0}" "$spawned_started_at"; then
    if [ "$mode" = "tmux" ]; then
      tmux kill-session -t "$session" >/dev/null 2>&1 || true
    elif [ -n "$spawned_pid" ]; then
      kill "$spawned_pid" >/dev/null 2>&1 || true
    fi
    rm -f "$(pid_file "$port")" "$run"
    [ "$target_type" != "file" ] || cleanup_private_file_root "$port" "$root" || true
    fail "could not write secure state file"
  fi

  make_urls "$port" "$url_path" "$bind_addr" ""
  if ! wait_for_local_url "$port" "$LOCAL_URL" "$bind_addr"; then
    stop_port_quiet "$port" || true
    printf 'STATUS=error\n'
    kv ERROR "server did not verify exact local URL"
    kv LOCAL_URL "$LOCAL_URL"
    kv PORT "$port"
    kv SESSION "$session"
    kv LOG "$log"
    exit 1
  fi
  if ! recorded_process_matches "$port" "$mode" "$session" "$root" "$bind_addr" \
      "${spawned_pid:-0}" "$spawned_started_at"; then
    stop_port_quiet "$port" || true
    fail "spawned preview identity did not survive local URL verification"
  fi

  if [ "$clear_tailscale_conflict" = "1" ]; then
    if ! clear_owned_tailscale_serve_for_port "$port"; then
      stop_port_quiet "$port" || true
      fail "existing tailscale serve mapping is foreign or could not be verified/cleared"
    fi
  fi

  if [ "$tailscale_serve" = "1" ]; then
    if ! command_exists tailscale; then
      stop_port_quiet "$port" || true
      fail "--tailscale-serve requires tailscale"
    fi
    tailnet_host="$(detect_tailnet_host 2>/dev/null || true)"
    if [ -z "$tailnet_host" ]; then
      stop_port_quiet "$port" || true
      fail "tailscale serve cannot start without a verifiable tailnet host"
    fi
    tailscale_enabled="1"
    tailscale_base_url="http://${tailnet_host}:${port}"

    mapping_status="$(tailscale_mapping_status "$port")"
    if [ "$mapping_status" != "absent" ]; then
      stop_port_quiet "$port" || true
      fail "tailscale serve port $port is already owned, foreign, or unverifiable ($mapping_status)"
    fi

    # Record cleanup intent before the external mutation. If the CLI succeeds
    # but later verification fails, stop_port_quiet retains enough evidence to
    # remove only this exact backend/mount.
    if ! write_state "$port" "$root" "$target" "$target_type" "$url_path" "$mode" "$bind_addr" \
        "$tailscale_enabled" "$tailscale_base_url" "${spawned_pid:-0}" "$spawned_started_at"; then
      stop_port_quiet "$port" || true
      fail "could not persist tailscale cleanup intent"
    fi
    if ! tailscale serve --bg --http="$port" --set-path=/ "http://127.0.0.1:${port}" >/dev/null 2>&1; then
      stop_port_quiet "$port" || true
      fail "tailscale serve failed for port $port"
    fi
    mapping_status="$(tailscale_mapping_status "$port")"
    if [ "$mapping_status" != "owned" ]; then
      stop_port_quiet "$port" || true
      fail "tailscale serve did not establish the exact owned mapping ($mapping_status)"
    fi
    if ! verify_url_once "${tailscale_base_url%/}${url_path}"; then
      stop_port_quiet "$port" || true
      fail "tailscale serve URL did not verify"
    fi
  fi

  BIND_ADDR="$bind_addr"
  TAILSCALE_SERVE_BASE_URL="$tailscale_base_url"
  if ! recorded_process_matches "$port" "$mode" "$session" "$root" "$bind_addr" \
      "${spawned_pid:-0}" "$spawned_started_at"; then
    stop_port_quiet "$port" || true
    fail "spawned preview identity changed before startup completed"
  fi
  if ! write_state "$port" "$root" "$target" "$target_type" "$url_path" "$mode" "$bind_addr" "$tailscale_enabled" "$tailscale_base_url" \
      "${spawned_pid:-0}" "$spawned_started_at"; then
    stop_port_quiet "$port" || true
    fail "could not write secure state file"
  fi
  emit_common ok "$port" "$root" "$target" "$target_type" "$url_path" "$mode"
  if [ "$port_note" != "requested" ]; then
    kv REQUESTED_PORT "$requested_port"
    kv PORT_NOTE "$port_note"
  fi
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

  local session mode root target target_type url_path status pid state_loaded="0" state_untrusted="0" state
  session="$(session_name "$port")"
  ROOT=""
  TARGET=""
  TARGET_TYPE="unknown"
  URL_PATH="/"
  PROCESS_MODE="unknown"
  BIND_ADDR="$DEFAULT_BIND_ADDR"
  TAILSCALE_SERVE_BASE_URL=""
  TAILSCALE_SERVE_ENABLED="0"
  STATE_PROCESS_PID="0"
  STATE_PROCESS_STARTED_AT=""
  state="$(state_file "$port")"
  if load_state_if_present "$port"; then
    state_loaded="1"
  elif [ -e "$state" ] || [ -L "$state" ]; then
    state_untrusted="1"
  fi
  root="${ROOT:-}"
  target="${TARGET:-}"
  target_type="${TARGET_TYPE:-unknown}"
  url_path="${URL_PATH:-/}"
  mode="${PROCESS_MODE:-unknown}"
  status="stopped"
  [ "$state_untrusted" = "0" ] || status="error"

  if [ "$state_loaded" = "1" ] && [ "$PROCESS_MODE" = "tmux" ] && has_tmux_session "$session" && \
      tmux_session_matches "$session" "$STATE_PROCESS_STARTED_AT"; then
    status="ok"
    mode="tmux"
  else
    pid="$STATE_PROCESS_PID"
    if [ "$state_loaded" = "1" ] && [ "$PROCESS_MODE" = "pid" ] && [ -n "$ROOT" ] && \
        [ -n "$pid" ] && pid_matches_server "$pid" "$port" "$ROOT" "$BIND_ADDR" \
          "$STATE_PROCESS_PID" "$STATE_PROCESS_STARTED_AT"; then
      status="ok"
      mode="pid"
    elif [ "$state_loaded" = "1" ] && [ "$PROCESS_MODE" = "pid" ] && kill -0 "$pid" 2>/dev/null; then
      status="error"
    fi
  fi

  if [ "$status" = "ok" ] && ! port_accepts_local_connection "$port" "$BIND_ADDR"; then
    status="degraded"
  fi
  make_urls "$port" "$url_path" "$BIND_ADDR" "$TAILSCALE_SERVE_BASE_URL"
  if [ "$status" = "ok" ] && ! verify_url_once "$LOCAL_URL"; then
    status="degraded"
  fi
  if [ "$status" = "ok" ] && [ "$TAILSCALE_SERVE_ENABLED" = "1" ] && \
      { [ -z "$TAILNET_URL" ] || ! verify_url_once "$TAILNET_URL"; }; then
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
  if stop_port_quiet "$port"; then
    kv STATUS ok
    kv STOPPED "$STOPPED_RESULT"
  else
    kv STATUS error
    kv STOPPED 0
    kv ERROR "$STOP_ERROR"
    kv PORT "$port"
    kv SESSION "$session"
    kv LOG "$log"
    exit 1
  fi
  kv PORT "$port"
  kv SESSION "$session"
  kv LOG "$log"
}

main() {
  if [ "$#" -gt 0 ]; then
    local command="$1"
    shift
    case "$command" in
      start) ensure_state_dir; start_server "$@" ;;
      status) ensure_state_dir; status_server "$@" ;;
      stop) ensure_state_dir; stop_server "$@" ;;
      -h|--help) usage ;;
      *) fail "unknown command: $command" ;;
    esac
  else
    usage
    exit 2
  fi
}

main "$@"
