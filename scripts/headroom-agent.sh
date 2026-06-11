#!/bin/bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  claudeh [headroom/claude args...]
  codexh [headroom/codex args...]
  omxh [omx args...]
  headroom-agent <claude|codex|omx> [...]

Environment knobs:
  HEADROOM_PORT              Proxy port (default: 8787)
  HEADROOM_MODE              Headroom mode (default: cache; set token for max compression)
  HEADROOM_WAIT_SECONDS      Proxy readiness wait (default: 60)
  HEADROOM_<TOOL>_CONTEXT_TOOL
                             1 to let Headroom inject RTK/lean-ctx instructions
                             (TOOL: CLAUDE, CODEX, or OMX; default 0)
  HEADROOM_<TOOL>_MCP        0 to skip temporary Headroom MCP registration
                             (default 1)
  HEADROOM_<TOOL>_SERENA     1 to let Headroom register Serena (default 0)
  HEADROOM_<TOOL>_MEMORY     1 to enable Headroom memory
  HEADROOM_<TOOL>_LEARN      1 to enable Headroom traffic learning
  HEADROOM_<TOOL>_CODE_GRAPH 1 to enable Headroom code graph proxy mode
USAGE
}

warn() { printf '[headroom-agent] %s\n' "$*" >&2; }

resolve_target() {
  local prog target
  prog="$(basename "$0")"
  case "$prog" in
    claudeh) printf 'claude\n' ;;
    codexh) printf 'codex\n' ;;
    omxh) printf 'omx\n' ;;
    headroom-agent|headroom-agent.sh)
      target="${1:-}"
      case "$target" in
        claude|codex|omx) printf '%s\n' "$target" ;;
        -h|--help|'') usage; exit 0 ;;
        *) warn "unknown target: $target"; usage >&2; exit 2 ;;
      esac
      ;;
    *) warn "unknown invocation name: $prog"; usage >&2; exit 2 ;;
  esac
}

port_open() {
  local port="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$port" <<'PY' >/dev/null 2>&1
import socket, sys
port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.4)
    sock.connect(("127.0.0.1", port))
PY
    return $?
  fi
  command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "$port" >/dev/null 2>&1
}

wait_for_proxy() {
  local port="$1"
  local wait_seconds="${HEADROOM_WAIT_SECONDS:-${HEADROOM_OMX_WAIT_SECONDS:-60}}"
  local deadline

  case "$wait_seconds" in
    ''|*[!0-9]*) wait_seconds=60 ;;
  esac
  [ "$wait_seconds" -gt 0 ] || return 0

  deadline=$((SECONDS + wait_seconds))
  while [ "$SECONDS" -le "$deadline" ]; do
    if command -v curl >/dev/null 2>&1; then
      curl -fsS "http://127.0.0.1:${port}/livez" >/dev/null 2>&1 && return 0
    else
      port_open "$port" && return 0
    fi
    sleep 0.25
  done
  return 1
}

is_headroom_proxy_ready() {
  local port="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "http://127.0.0.1:${port}/livez" >/dev/null 2>&1
    return $?
  fi
  port_open "$port"
}

run_headroom_wrap() {
  local target="$1"
  shift
  local port="${HEADROOM_PORT:-8787}"
  local upper
  local -a args

  if ! command -v headroom >/dev/null 2>&1; then
    warn "headroom not found. Run: bash ~/work/dotfiles/scripts/headroom.sh"
    exit 127
  fi

  upper="$(printf '%s' "$target" | tr '[:lower:]' '[:upper:]')"
  export HEADROOM_MODE="${HEADROOM_MODE:-cache}"
  export HEADROOM_AGENT_ACTIVE="$target"

  args=(wrap "$target" --port "$port")
  # Default shell entrypoints should not silently rewrite arbitrary project
  # guidance or duplicate Serena registrations. Enable explicitly per tool.
  if [ "$(env_flag "HEADROOM_${upper}_CONTEXT_TOOL" 0)" != "1" ]; then
    args+=(--no-context-tool)
  fi
  if [ "$(env_flag "HEADROOM_${upper}_MCP" 1)" = "0" ]; then
    args+=(--no-mcp)
  fi
  if [ "$(env_flag "HEADROOM_${upper}_SERENA" 0)" != "1" ]; then
    args+=(--no-serena)
  fi
  [ "$(env_flag "HEADROOM_${upper}_MEMORY" 0)" = "1" ] && args+=(--memory)
  [ "$(env_flag "HEADROOM_${upper}_LEARN" 0)" = "1" ] && args+=(--learn)
  [ "$(env_flag "HEADROOM_${upper}_CODE_GRAPH" 0)" = "1" ] && args+=(--code-graph)

  exec headroom "${args[@]}" "$@"
}

env_flag() {
  local name="$1" default="$2" value
  value="${!name:-$default}"
  printf '%s\n' "$value"
}

run_codex_config_wrapped() {
  local target="$1"
  local command_name="$2"
  shift 2
  local port="${HEADROOM_PORT:-8787}"
  local config_dir="${CODEX_HOME:-$HOME/.codex}"
  local config_file="$config_dir/config.toml"
  local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/headroom-agent/codex-config"
  local upper label lock_dir sessions_dir managed_file session_file neutralized_provider_file
  local proxy_started=0
  local proxy_pid=""
  local session_registered=0
  local status=0
  local -a proxy_args prepare_args launch_args

  label="${target}h"
  upper="$(printf '%s' "$target" | tr '[:lower:]' '[:upper:]')"
  if ! command -v headroom >/dev/null 2>&1; then
    warn "headroom not found. Run: bash ~/work/dotfiles/scripts/headroom.sh"
    exit 127
  fi
  if ! command -v "$command_name" >/dev/null 2>&1; then
    warn "$command_name not found in PATH"
    exit 127
  fi
  if [ -n "${CODEX_HOME:-}" ] && [ "${CODEX_HOME%/}" != "$HOME/.codex" ]; then
    warn "$label currently supports Headroom's default Codex config path only (~/.codex)."
    warn "Unset CODEX_HOME or run direct headroom/codex wrapping for custom CODEX_HOME=$CODEX_HOME."
    exit 1
  fi
  if [ -L "$config_file" ]; then
    warn "$config_file is a symlink; refusing to let Headroom mutate a tracked template."
    warn "Run scripts/codex.sh once to replace it with a managed live config, then retry."
    exit 1
  fi

  export HEADROOM_MODE="${HEADROOM_MODE:-cache}"
  export HEADROOM_AGENT_ACTIVE="$target"
  sessions_dir="$state_dir/sessions"
  lock_dir="$state_dir/config.lock"
  managed_file="$state_dir/managed-by-headroom-agent"
  neutralized_provider_file="$state_dir/neutralized-model-provider"
  session_file="$sessions_dir/session-$$"
  mkdir -p "$sessions_dir"

  acquire_config_lock() {
    local tries=0 lock_pid=""
    while ! mkdir "$lock_dir" 2>/dev/null; do
      if [ -f "$lock_dir/pid" ]; then
        lock_pid="$(cat "$lock_dir/pid" 2>/dev/null || true)"
        if [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" >/dev/null 2>&1; then
          rm -rf "$lock_dir"
          continue
        fi
      fi
      tries=$((tries + 1))
      if [ "$tries" -ge 200 ]; then
        warn "timed out waiting for Codex-config Headroom lock: $lock_dir"
        return 1
      fi
      sleep 0.1
    done
    printf '%s\n' "$$" > "$lock_dir/pid"
  }

  release_config_lock() {
    rm -rf "$lock_dir"
  }

  cleanup_stale_sessions() {
    local file pid
    for file in "$sessions_dir"/*; do
      [ -e "$file" ] || continue
      pid="$(awk '{print $1}' "$file" 2>/dev/null || true)"
      if [ -z "$pid" ] || ! kill -0 "$pid" >/dev/null 2>&1; then
        rm -f "$file"
      fi
    done
  }

  active_session_count() {
    find "$sessions_dir" -type f -name 'session-*' 2>/dev/null | wc -l | tr -d ' '
  }

  active_session_port() {
    local file
    file="$(find "$sessions_dir" -type f -name 'session-*' 2>/dev/null | head -1)"
    [ -n "$file" ] || return 0
    awk '{print $2}' "$file" 2>/dev/null || true
  }

  config_has_headroom_marker() {
    [ -f "$config_file" ] && grep -q 'Headroom proxy (auto-injected by headroom wrap codex)' "$config_file"
  }

  neutralize_top_level_model_provider() {
    command -v python3 >/dev/null 2>&1 || return 0
    python3 - "$config_file" "$neutralized_provider_file" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

config = Path(sys.argv[1])
state = Path(sys.argv[2])
if not config.exists():
    raise SystemExit(0)

lines = config.read_text(encoding="utf-8").splitlines(keepends=True)
out: list[str] = []
changed = False
in_headroom_block = False
seen_table = False
pattern = re.compile(r"^(\s*)model_provider\s*=")
marker = "  # disabled by headroom-agent: Headroom injects a temporary provider"

for line in lines:
    stripped = line.strip()
    if stripped == "# --- Headroom proxy (auto-injected by headroom wrap codex) ---":
        in_headroom_block = True
        out.append(line)
        continue
    if stripped == "# --- end Headroom ---":
        out.append(line)
        in_headroom_block = False
        continue
    if not in_headroom_block and not seen_table and pattern.match(line):
        newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if newline else line
        out.append(f"# {body}{marker}{newline}")
        changed = True
        continue
    if not in_headroom_block and re.match(r"^\s*\[", line):
        seen_table = True
    out.append(line)

if changed:
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("1\n", encoding="utf-8")
    tmp = config.with_suffix(config.suffix + ".headroom-agent-tmp")
    tmp.write_text("".join(out), encoding="utf-8")
    tmp.replace(config)
PY
  }

  restore_top_level_model_provider() {
    [ -f "$neutralized_provider_file" ] || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    python3 - "$config_file" "$neutralized_provider_file" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

config = Path(sys.argv[1])
state = Path(sys.argv[2])
if not config.exists():
    state.unlink(missing_ok=True)
    raise SystemExit(0)

marker = "  # disabled by headroom-agent: Headroom injects a temporary provider"
pattern = re.compile(rf"^# (\s*model_provider\s*=.*?){re.escape(marker)}(\n?)$")
changed = False
out: list[str] = []
for line in config.read_text(encoding="utf-8").splitlines(keepends=True):
    match = pattern.match(line)
    if match:
        out.append(f"{match.group(1)}{match.group(2)}")
        changed = True
    else:
        out.append(line)

if changed:
    tmp = config.with_suffix(config.suffix + ".headroom-agent-tmp")
    tmp.write_text("".join(out), encoding="utf-8")
    tmp.replace(config)
state.unlink(missing_ok=True)
PY
  }

  register_codex_config_session() {
    local count existing_port was_prewrapped managed
    acquire_config_lock || exit 1
    cleanup_stale_sessions
    count="$(active_session_count)"
    if [ "$count" -gt 0 ]; then
      existing_port="$(active_session_port)"
      if [ "$existing_port" != "$port" ]; then
        release_config_lock
        warn "another Codex-config Headroom session is already using port $existing_port; refusing port $port"
        exit 1
      fi
      printf '%s %s %s\n' "$$" "$port" "$target" > "$session_file"
      session_registered=1
      release_config_lock
      return 0
    fi

    was_prewrapped=0
    config_has_headroom_marker && was_prewrapped=1
    neutralize_top_level_model_provider
    prepare_args=(wrap codex --port "$port" --prepare-only)
    # Default shell entrypoints are conservative: no project guidance rewrites
    # and no duplicate Serena registration unless explicitly enabled.
    if [ "$(env_flag "HEADROOM_${upper}_CONTEXT_TOOL" 0)" != "1" ]; then
      prepare_args+=(--no-context-tool)
    fi
    [ "$(env_flag "HEADROOM_${upper}_MCP" 1)" = "0" ] && prepare_args+=(--no-mcp)
    if [ "$(env_flag "HEADROOM_${upper}_SERENA" 0)" != "1" ]; then
      prepare_args+=(--no-serena)
    fi
    [ "$(env_flag "HEADROOM_${upper}_MEMORY" 0)" = "1" ] && prepare_args+=(--memory)

    if ! headroom "${prepare_args[@]}"; then
      restore_top_level_model_provider
      release_config_lock
      exit 1
    fi

    managed=1
    [ "$was_prewrapped" -eq 1 ] && managed=0
    printf '%s\n' "$managed" > "$managed_file"
    printf '%s %s %s\n' "$$" "$port" "$target" > "$session_file"
    session_registered=1
    release_config_lock
  }

  cleanup() {
    status="${1:-$?}"
    trap - EXIT INT TERM HUP
    set +e
    if [ "$session_registered" -eq 1 ]; then
      if acquire_config_lock; then
        rm -f "$session_file"
        cleanup_stale_sessions
        if [ "$(active_session_count)" -eq 0 ]; then
          if [ "$(cat "$managed_file" 2>/dev/null || printf '0')" = "1" ]; then
            headroom unwrap codex --port "$port" --no-stop-proxy >/dev/null 2>&1 \
              || warn "headroom unwrap codex failed; run manually: headroom unwrap codex --port $port"
            restore_top_level_model_provider
          fi
          rm -f "$managed_file"
        fi
        release_config_lock
      else
        warn "could not acquire cleanup lock; run manually if needed: headroom unwrap codex --port $port"
      fi
    fi
    if [ "$proxy_started" -eq 1 ] && [ -n "$proxy_pid" ]; then
      kill "$proxy_pid" >/dev/null 2>&1 || true
      wait "$proxy_pid" >/dev/null 2>&1 || true
    fi
    exit "$status"
  }
  trap cleanup EXIT INT TERM HUP

  proxy_args=(proxy --port "$port")
  [ "$(env_flag "HEADROOM_${upper}_MEMORY" 0)" = "1" ] && proxy_args+=(--memory)
  [ "$(env_flag "HEADROOM_${upper}_LEARN" 0)" = "1" ] && proxy_args+=(--learn)
  [ "$(env_flag "HEADROOM_${upper}_CODE_GRAPH" 0)" = "1" ] && proxy_args+=(--code-graph)

  if port_open "$port"; then
    if is_headroom_proxy_ready "$port"; then
      warn "reusing existing Headroom-compatible proxy port $port"
    else
      warn "port $port is already in use but does not look like Headroom (/livez failed)"
      exit 1
    fi
  else
    local log_dir log_file
    log_dir="${HEADROOM_LOG_DIR:-$HOME/Library/Logs}"
    mkdir -p "$log_dir"
    log_file="$log_dir/headroom-${label}.log"
    headroom "${proxy_args[@]}" >>"$log_file" 2>&1 &
    proxy_pid=$!
    proxy_started=1
    if ! wait_for_proxy "$port"; then
      warn "Headroom proxy did not become ready on port $port; log: $log_file"
      exit 1
    fi
  fi

  register_codex_config_session

  launch_args=("$@")
  # Mirror configs/.zshrc: normal interactive OMX launches get the user's
  # preferred flags; subcommands (setup/doctor/exec/...) remain untouched.
  contains_launch_arg() {
    local expected="$1" arg
    for arg in "${launch_args[@]}"; do
      [ "$arg" = "$expected" ] && return 0
    done
    return 1
  }

  contains_reasoning_arg() {
    local arg
    for arg in "${launch_args[@]}"; do
      case "$arg" in
        --low|--medium|--high|--xhigh|--reasoning-effort|--reasoning-effort=*)
          return 0
          ;;
      esac
    done
    return 1
  }

  if [ "$target" = "omx" ] && [ "${OMX_DEFAULT_FLAGS:-1}" != "0" ] && { [ "${#launch_args[@]}" -eq 0 ] || [[ "${launch_args[0]}" == -* ]]; }; then
    local -a default_omx_args
    contains_launch_arg --direct || default_omx_args+=(--direct)
    contains_reasoning_arg || default_omx_args+=(--xhigh)
    contains_launch_arg --madmax || default_omx_args+=(--madmax)
    if [ "${#default_omx_args[@]}" -gt 0 ]; then
      if [ "${#launch_args[@]}" -eq 0 ]; then
        launch_args=("${default_omx_args[@]}")
      else
        launch_args=("${default_omx_args[@]}" "${launch_args[@]}")
      fi
    fi
  fi

  set +e
  if [ "${#launch_args[@]}" -eq 0 ]; then
    "$command_name"
  else
    "$command_name" "${launch_args[@]}"
  fi
  status=$?
  set -e
  cleanup "$status"
}

target="$(resolve_target "$@")"
case "$(basename "$0")" in
  headroom-agent|headroom-agent.sh) shift || true ;;
esac

if [ "$target" != "claude" ] && { [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; }; then
  usage
  exit 0
fi

case "$target" in
  claude) run_headroom_wrap claude "$@" ;;
  codex) run_codex_config_wrapped codex codex "$@" ;;
  omx) run_codex_config_wrapped omx omx "$@" ;;
esac
