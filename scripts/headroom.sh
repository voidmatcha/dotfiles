#!/bin/bash
set -euo pipefail
TAG="headroom"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

HEADROOM_INSTALL_SPEC="${HEADROOM_INSTALL_SPEC:-headroom-ai[proxy,mcp,code]}"
HEADROOM_PYTHON="${HEADROOM_PYTHON:-3.13}"
WRAPPER_SRC="$DOTFILES_DIR/scripts/headroom-agent.sh"
WRAPPER_DIR="$HOME/.local/bin"

install_headroom_cli() {
  info "Checking headroom..."
  if $DRY_RUN; then
    info "[dry-run] uv tool install -p $HEADROOM_PYTHON '$HEADROOM_INSTALL_SPEC'"
    $UPGRADE && info "[dry-run] would: uv tool upgrade --all (headroom-ai, serena-agent, …)"
    return 0
  fi

  if command -v headroom &>/dev/null; then
    info "headroom already installed ($(headroom --version 2>/dev/null || echo unknown))"
    # --upgrade: bump ALL uv-managed tools in one pass (headroom-ai, serena-agent, …).
    if $UPGRADE && command -v uv &>/dev/null; then
      info "Upgrading uv tools (--upgrade)..."
      uv tool upgrade --all || warn "uv tool upgrade reported errors (continuing)"
    fi
    return 0
  fi

  if command -v uv &>/dev/null; then
    info "Installing headroom via uv tool ($HEADROOM_INSTALL_SPEC)..."
    if uv tool install -p "$HEADROOM_PYTHON" "$HEADROOM_INSTALL_SPEC"; then
      info "headroom installed"
      return 0
    fi
    warn "uv tool install failed — trying pipx fallback"
  fi

  if command -v pipx &>/dev/null; then
    if pipx install "$HEADROOM_INSTALL_SPEC"; then
      info "headroom installed via pipx"
      return 0
    fi
    warn "pipx install failed"
  else
    warn "pipx not found"
  fi

  warn "headroom install failed — try manually: uv tool install -p $HEADROOM_PYTHON '$HEADROOM_INSTALL_SPEC'"
  return 0
}

install_headroom_wrappers() {
  local name
  if $DRY_RUN; then
    for name in headroom-agent claudeh codexh omxh; do
      info "[dry-run] ln -sf $WRAPPER_SRC -> $WRAPPER_DIR/$name"
    done
    return 0
  fi

  ensure_dir "$WRAPPER_DIR"
  chmod +x "$WRAPPER_SRC"
  for name in headroom-agent claudeh codexh omxh; do
    ln -sf "$WRAPPER_SRC" "$WRAPPER_DIR/$name"
    info "Installed wrapper: $WRAPPER_DIR/$name"
  done
}

install_headroom_daemon() {
  # Persistent shared proxy (LaunchAgent) so concurrent agent sessions reuse ONE
  # session-independent proxy instead of each `wrap` binding the port — upstream
  # has no auto-free-port (#1121), and an ad-hoc wrap proxy dies with the session
  # that started it. The claudeh/codexh/omxh wrappers attach to it (claude via
  # `--no-proxy`, codex/omx already reuse). Opt out: HEADROOM_DAEMON=0.
  # Configures ONLY claude (`--providers manual --target claude`) so it does NOT
  # re-inject the codex provider — codex stays bypassed (HEADROOM_CODEX=0; routing
  # codex /v1/responses through the proxy is broken upstream, #79).
  local port="${HEADROOM_PORT:-8787}"
  # Respect the global Headroom bypass too, not just the daemon-specific knob, so
  # users who set HEADROOM_DEFAULT=0 / HEADROOM_DISABLE=1 don't get an install-time
  # persistent service they opted out of. (per codex review)
  if [ "${HEADROOM_DEFAULT:-1}" = "0" ] || [ "${HEADROOM_DISABLE:-0}" = "1" ] || [ "${HEADROOM_DAEMON:-1}" = "0" ]; then
    info "Headroom disabled (DEFAULT/DISABLE/DAEMON) -> skipping persistent proxy"
    return 0
  fi
  if $DRY_RUN; then
    info "[dry-run] headroom install apply --port $port --providers manual --target claude"
    return 0
  fi
  command -v headroom &>/dev/null || { warn "headroom CLI missing; skipping daemon"; return 0; }
  # Don't fight a proxy that's already live on the port (an interactive wrap
  # session, or an existing daemon). (Re)apply later from a shell with no agent
  # bound to :$port, when binding is safe.
  if curl -fsS --max-time 3 "http://127.0.0.1:$port/livez" &>/dev/null; then
    warn "Headroom proxy already live on :$port; not touching it. To (re)install the"
    warn "  persistent service, run from a shell with NO live agent on :$port:"
    warn "    headroom install apply --port $port --providers manual --target claude"
    return 0
  fi
  if headroom install apply --port "$port" --providers manual --target claude &>/dev/null; then
    info "Headroom persistent proxy (LaunchAgent) applied on :$port"
  else
    warn "headroom install apply failed; run manually outside a live agent session:"
    warn "  headroom install apply --port $port --providers manual --target claude"
  fi
}

install_headroom_cli
install_headroom_wrappers
install_headroom_daemon
info "Headroom setup done (persistent proxy unless HEADROOM_DAEMON=0; claude/codex/omx route via wrappers, reuse the shared proxy; HEADROOM_DEFAULT=0 to bypass)"
