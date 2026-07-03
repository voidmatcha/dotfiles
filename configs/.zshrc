# ── Oh My Zsh ──
# macOS does not ship the Linux-style C.UTF-8 locale. Some tools inherit it
# from remote/container sessions, which makes every bash child print locale
# warnings. Drop only that invalid value and let LANG drive the locale.
if [[ "$(uname -s)" == "Darwin" && "${LC_ALL:-}" == "C.UTF-8" ]]; then
  unset LC_ALL
fi
if [[ "$(uname -s)" == "Darwin" && "${LC_CTYPE:-}" == "C.UTF-8" ]]; then
  unset LC_CTYPE
fi

export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME="robbyrussell"

plugins=(
  git
  zsh-autosuggestions
  zsh-syntax-highlighting
  zsh-completions
  docker
  fzf
)

fpath+=${ZSH_CUSTOM:-${ZSH:-~/.oh-my-zsh}/custom}/plugins/zsh-completions/src

source "$ZSH/oh-my-zsh.sh"

# ── Local bin (early — uv tool installs go here, serena check below needs it) ──
export PATH="$HOME/.local/bin:$PATH"

# ── Headroom default agent entrypoints ──
# When installed, route normal Claude/Codex/OMX launches through Headroom's
# cache/proxy wrappers. This is intentionally shell-level only: `command claude`,
# `command codex`, `command omx`, or `HEADROOM_DEFAULT=0` bypasses it instantly.
# context-check remains advisory and optional; a missing probe should not
# prevent Headroom-backed entry.
export HEADROOM_MODE="${HEADROOM_MODE:-cache}"
# Keep the proxy single-process by default. Headroom's CCR retrieval store,
# compression cache, prefix tracker, and TOIN state are process-local; multiple
# uvicorn workers can strand `<<ccr:...>>` markers on a different worker than
# `headroom_retrieve`. Override only when accepting that tradeoff, e.g.
# `HEADROOM_WORKERS=4 claudeh`.
#
# The `:-1` default cannot override a value already exported by a parent shell
# or a long-lived tmux server, so a stale multi-worker value would otherwise
# stick across every child pane and silently strand `<<ccr:...>>` markers under
# concurrent fan-out (e.g. workflows). Reset anything but the safe default for
# interactive shells; the per-command override above bypasses this rc and works.
export HEADROOM_WORKERS="${HEADROOM_WORKERS:-1}"
[ "$HEADROOM_WORKERS" = 1 ] || export HEADROOM_WORKERS=1

# Avoid retry amplification: Headroom should return transient 5xx quickly and
# let the interactive client own user-visible retry/backoff.
export HEADROOM_RETRY_MAX_ATTEMPTS="${HEADROOM_RETRY_MAX_ATTEMPTS:-1}"

# If Headroom's pre-upstream compression times out on a very large Codex/OMX
# request, fail open and forward the original request instead of closing the
# stream (the proxy otherwise returns 413 / WS 1009 and Codex reports
# "stream disconnected before completion").
export HEADROOM_WS_FAIL_OPEN_ON_COMPRESSION_FAILURE="${HEADROOM_WS_FAIL_OPEN_ON_COMPRESSION_FAILURE:-1}"

# Disable Anthropic usage polling only; this does not affect Claude auth/login.
export HEADROOM_NO_SUBSCRIPTION_TRACKING="${HEADROOM_NO_SUBSCRIPTION_TRACKING:-1}"

# Keep plain OMX launches direct by default. Codex already exposes the
# useful session details via [tui].status_line, so the managed OMX tmux
# HUD pane is opt-in (`omx --tmux` or OMX_LAUNCH_POLICY=tmux).
# NOTE: 절반은 취향(status_line 중복 회피), 절반은 아래 WORKAROUND의 발생원 차단.
# 업스트림 픽스 후에도 유지 가능하지만, HUD를 다시 기본으로 쓰려면 이 줄만 빼면 됨.
export OMX_LAUNCH_POLICY="${OMX_LAUNCH_POLICY:-direct}"

# Codex bypasses Headroom by default (direct to OpenAI); Claude/OMX still proxy.
# Why: new Codex (cli >=0.117 / gpt-5.4+) streams /v1/responses over WebSocket,
# and the upstream relay for it (headroomlabs-ai/headroom #79) is still
# open/stale with no merged upstream PR as of headroom-ai 0.27.0 — so routing
# Codex through the proxy isn't guaranteed (#82 = the 403-on-WS-upgrade repro).
# The related WS-1009 crash (#531) IS already fixed (v0.24.0). Keeping Codex
# direct avoids the risk. Re-enable once #79 ships: HEADROOM_CODEX=1 (or run
# `headroom wrap codex` for a one-off), then verify with `headroom doctor`.
export HEADROOM_CODEX="${HEADROOM_CODEX:-0}"

__headroom_default_enabled() {
  local tool value
  tool="$1"
  [ "${HEADROOM_DEFAULT:-1}" != "0" ] || return 1
  [ "${HEADROOM_DISABLE:-0}" != "1" ] || return 1
  case "$tool" in
    claude) value="${HEADROOM_CLAUDE:-1}" ;;
    codex) value="${HEADROOM_CODEX:-1}" ;;
    omx) value="${HEADROOM_OMX:-1}" ;;
    *) value=1 ;;
  esac
  [ "$value" != "0" ]
}

__headroom_wrapper_available() {
  command -v "$1" &>/dev/null && command -v headroom &>/dev/null
}

# ── Rancher Desktop (optional, Docker CLI replacement) ──
[ -d "$HOME/.rd/bin" ] && export PATH="$HOME/.rd/bin:$PATH"

# ── nvm ──
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"

# ── pyenv ──
export PYENV_ROOT="$HOME/.pyenv"
[[ -d "$PYENV_ROOT/bin" ]] && export PATH="$PYENV_ROOT/bin:$PATH"
command -v pyenv &>/dev/null && eval "$(pyenv init - --no-rehash)"

# ── SDKMAN ──
export SDKMAN_DIR="$HOME/.sdkman"
[[ -s "$SDKMAN_DIR/bin/sdkman-init.sh" ]] && source "$SDKMAN_DIR/bin/sdkman-init.sh"

# ── zoxide ──
command -v zoxide &>/dev/null && eval "$(zoxide init zsh)"

# ── fzf ──
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# ── atuin ──
command -v atuin &>/dev/null && eval "$(atuin init zsh --disable-up-arrow)"

# ── direnv ──
command -v direnv &>/dev/null && eval "$(direnv hook zsh)"

# ── Claude Code: Headroom default + serena system-prompt override ──
# Headroom is used when available; otherwise this falls back to plain `claude`.
# Serena's prompt-override counteracts Opus/Claude Code bias against external
# MCP tools. Disable Headroom per invocation with HEADROOM_DEFAULT=0 or
# HEADROOM_CLAUDE=0; bypass the function entirely with `command claude`.
if command -v claude &>/dev/null; then
  claude() {
    local -a extra
    # serena prompt override (optional — skipped if serena absent).
    if command -v serena &>/dev/null; then
      local override
      override="$(serena prompts print-cc-system-prompt-override 2>/dev/null)"
      [ -n "$override" ] && extra+=(--system-prompt="$override")
    fi
    if __headroom_default_enabled claude && __headroom_wrapper_available claudeh; then
      command claudeh ${extra[@]+"${extra[@]}"} "$@"
    else
      command claude ${extra[@]+"${extra[@]}"} "$@"
    fi
  }
fi

# ── Codex CLI: Headroom default ──
if command -v codex &>/dev/null; then
  codex() {
    if __headroom_default_enabled codex && __headroom_wrapper_available codexh; then
      command codexh "$@"
    else
      command codex "$@"
    fi
  }
fi

# ── omx (oh-my-codex): Headroom default + launch flags ──

# Guard raw OMX HUD watches so repeated shells/commands do not stack panes/processes.
# `omx hud --tmux` remains the preferred managed HUD surface; this only catches
# accidental raw `omx hud --watch` invocations before they fork another watcher.
# NOTE: 위 WORKAROUND와 같은 증상군이지만 이쪽은 사용자 실수 방지 보험이라
# 업스트림 픽스 후에도 잔류 무해 (제거 의무 없음).

# WORKAROUND(oh-my-codex@0.18.11, 소스 검증 2026-06-12):
# 1) 확인된 업스트림 결함 — hooks/extensibility/dispatcher.js가 process.env를
#    통째 상속해 훅이 OMX_TMUX_HUD_* 를 물려받아 pane을 재생성할 수 있음
#    (team/tmux-session.js의 scrubTeamWorkerHudOwnershipEnv와 비대칭 = 누락).
#    이슈 등록 대상: https://github.com/Yeachan-Heo/oh-my-codex/issues (TBD)
# 2) 정상 종료 시 정리는 업스트림이 이미 함(cli finally) — 고아 pane은 강제
#    종료(cmux 탭 강제 닫기 등, finally 미실행)에서만 생김. 이 함수는 그 보험.
# 비용: 매 프롬프트(precmd) 전체 pane 스캔 + pane당 ps 2회.
# 롤백 조건: 훅 env scrub이 업스트림에 들어가면 재생성 경로가 사라지므로
# precmd 등록을 빼고, 강제 종료 잔존만 감수하거나 수동 정리로 격하 검토.
__dotfiles_cleanup_orphan_hud_panes() {
  [[ -n "${TMUX:-}" ]] || return 0
  command -v tmux >/dev/null 2>&1 || return 0

  local pane pid command cwd args envline leader
  while IFS=$'\t' read -r pane pid command cwd; do
    [[ -n "$pane" && -n "$pid" ]] || continue
    args="$(ps -ww -o args= -p "$pid" 2>/dev/null)" || continue

    if [[ "$args" == *"codex-hud"* ]]; then
      [[ -n "${GP_CODEX_HUD_DISABLE:-}" ]] || continue
      tmux kill-pane -t "$pane" >/dev/null 2>&1 || true
      continue
    fi

    [[ "$args" == *"oh-my-codex/dist/cli/omx.js hud --watch"* ]] || continue
    envline="$(ps eww -p "$pid" 2>/dev/null)" || envline=""
    leader="$(printf '%s\n' "$envline" | sed -n 's/.*OMX_TMUX_HUD_LEADER_PANE=\([^ ]*\).*/\1/p' | head -1)"

    # Keep a live, intentionally managed OMX HUD. Remove only panes whose leader
    # disappeared, which is the common stale bottom-HUD case after OMX exits.
    if [[ -n "$leader" ]] && tmux display-message -p -t "$leader" '#{pane_id}' >/dev/null 2>&1; then
      continue
    fi

    tmux kill-pane -t "$pane" >/dev/null 2>&1 || true
  done < <(tmux list-panes -a -F '#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}' 2>/dev/null)
}

__dotfiles_cleanup_orphan_hud_panes >/dev/null 2>&1 || true
precmd_functions+=(__dotfiles_cleanup_orphan_hud_panes)

__dotfiles_omx_hud_watch_running() {
  pgrep -f 'oh-my-codex/dist/cli/omx\.js hud --watch' >/dev/null 2>&1
}

__dotfiles_omx_hud_watch_guard() {
  [[ "$1" == "hud" ]] || return 1
  shift

  local arg
  for arg in "$@"; do
    [[ "$arg" == "--watch" || "$arg" == "-w" ]] || continue
    if __dotfiles_omx_hud_watch_running; then
      echo "omx hud --watch already running; use 'omx hud --tmux' or 'omx hud --reconcile-tmux'." >&2
      return 0
    fi
    return 1
  done

  return 1
}
# Headroom is used when available; otherwise every interactive launch still gets
# --direct (no OMX tmux/HUD management), --xhigh (reasoning effort), and
# --madmax (bypass Codex approvals/sandbox — intentional, mirrors Claude's auto
# permission mode). Subcommands (setup/doctor/exec/…) are left untouched.
# Disable Headroom with HEADROOM_DEFAULT=0/HEADROOM_OMX=0; disable flag injection
# with OMX_DEFAULT_FLAGS=0.
if command -v omx &>/dev/null; then
  omx() {
  if __dotfiles_omx_hud_watch_guard "$@"; then
    return 0
  fi
    if __headroom_default_enabled omx && __headroom_wrapper_available omxh; then
      command omxh "$@"
      return $?
    fi
    if [ "${OMX_DEFAULT_FLAGS:-1}" != "0" ] && { [ $# -eq 0 ] || [[ "$1" == -* ]]; }; then
      command omx --direct --xhigh --madmax "$@"
    else
      command omx "$@"
    fi
  }
fi

# ── User-local secrets (optional, gitignored everywhere) ──
# Loaded if present. Use this for API keys (EXA_API_KEY when paid plan,
# OPENAI_API_KEY for local scripts, etc.). Most MCP servers in this dotfiles
# run keyless on free tiers, so this file is optional.
[ -f "$HOME/.dev.secrets.env" ] && . "$HOME/.dev.secrets.env"

# ── Company-local secrets (optional) ──
# Loaded if present; managed by the company overlay (see dotfiles/company/).
[ -f "$HOME/.company.secrets.env" ] && . "$HOME/.company.secrets.env"

# ── Company-local shell overlay (optional) ──
# Symlinked from dotfiles/company/configs/zshrc-overlay.sh by company/install.sh.
# Used for shell hooks that should only run on company machines (e.g. Codex HUD).

# The optional company overlay can source GP Codex HUD, which creates a
# tmux split. Keep it off by default to avoid a second HUD beside Codex
# built-in status_line/explicit OMX HUD. Set GP_CODEX_HUD_DISABLE= to opt in.
export GP_CODEX_HUD_DISABLE="${GP_CODEX_HUD_DISABLE-1}"
[ -f "$HOME/.company.zshrc.sh" ] && . "$HOME/.company.zshrc.sh"

# Company overlays may define their own agent functions (for example Codex HUD).
# Re-apply the Headroom entrypoint as the outermost wrapper, but preserve the
# overlay function as the fallback when Headroom is disabled or unavailable.
if typeset -f claude >/dev/null; then
  functions[__dotfiles_claude_base]="${functions[claude]}"
fi
if typeset -f codex >/dev/null; then
  functions[__dotfiles_codex_base]="${functions[codex]}"
fi
if typeset -f omx >/dev/null; then
  functions[__dotfiles_omx_base]="${functions[omx]}"
fi

if command -v claude &>/dev/null || typeset -f claude >/dev/null; then
  claude() {
    if __headroom_default_enabled claude && __headroom_wrapper_available claudeh; then
      local -a extra
      if command -v serena &>/dev/null; then
        local override
        override="$(serena prompts print-cc-system-prompt-override 2>/dev/null)"
        [ -n "$override" ] && extra+=(--system-prompt="$override")
      fi
      command claudeh ${extra[@]+"${extra[@]}"} "$@"
    elif typeset -f __dotfiles_claude_base >/dev/null; then
      __dotfiles_claude_base "$@"
    else
      command claude "$@"
    fi
  }
fi

if command -v codex &>/dev/null || typeset -f codex >/dev/null; then
  codex() {
    if __headroom_default_enabled codex && __headroom_wrapper_available codexh; then
      command codexh "$@"
    elif typeset -f __dotfiles_codex_base >/dev/null; then
      __dotfiles_codex_base "$@"
    else
      command codex "$@"
    fi
  }
fi

if command -v omx &>/dev/null || typeset -f omx >/dev/null; then
  omx() {
  if __dotfiles_omx_hud_watch_guard "$@"; then
    return 0
  fi
    if __headroom_default_enabled omx && __headroom_wrapper_available omxh; then
      command omxh "$@"
    elif typeset -f __dotfiles_omx_base >/dev/null; then
      __dotfiles_omx_base "$@"
    elif [ "${OMX_DEFAULT_FLAGS:-1}" != "0" ] && { [ $# -eq 0 ] || [[ "$1" == -* ]]; }; then
      command omx --direct --xhigh --madmax "$@"
    else
      command omx "$@"
    fi
  }
fi

# ── Tailscale dev-server bind helpers ──
# Returns Tailscale IPv4 address, or empty string if not connected.
ts_ip() {
  command -v tailscale &>/dev/null && tailscale ip -4 2>/dev/null
}

# Auto-export DEV_HOST when Tailscale is up. Many tools (Vite, Next, Rails,
# uvicorn) honor HOST or HOST-like env vars; you can also reference $DEV_HOST
# directly in flags: e.g., `next dev -H "$DEV_HOST"`.
__ts_ip="$(ts_ip)"
if [ -n "$__ts_ip" ]; then
  export DEV_HOST="$__ts_ip"
fi
unset __ts_ip

# Print bind recipes for common dev servers (call this when you forget the flag).
ts-bind-help() {
  local ip
  ip=$(ts_ip)
  if [ -z "$ip" ]; then
    echo "Tailscale not connected. Run: tailscale up" >&2
    return 1
  fi
  cat <<EOF
Your Tailscale IP: $ip
DEV_HOST env var:  ${DEV_HOST:-(not set)}

Bind common dev servers to tailnet only (other devices on cafe wifi
cannot reach these — only authenticated tailnet peers can):

  Frontend:
    next dev -H $ip -p 3000
    vite --host $ip --port 5173
    pnpm dev --host $ip
    rails server -b $ip -p 3000

  Backend:
    python -m http.server 8000 --bind $ip
    uvicorn app:app --host $ip --port 8000
    flask run --host $ip --port 5000
    node server.js          # set HOST=$ip in env

Pro tip: set HOST=\$DEV_HOST in your shell to make most tools auto-bind:
  HOST=\$DEV_HOST npm start
EOF
}

# ── Aliases ──
alias ls="eza"
alias ll="eza -la"
alias lt="eza --tree --level=2"
alias cat="bat"
alias g="git"
alias gs="git status"
alias gd="git diff"
alias gl="git log --oneline --graph"
alias gp="git push"
alias gc="git commit"

# Enable 1h prompt-cache TTL (vs 5min default) for Anthropic API
export ENABLE_PROMPT_CACHING_1H=1

# Enable RTK hook rewrite audit locally so safety reports can count bypass,
# fallback, and repeat-after-compression candidates without storing outputs.
export RTK_HOOK_AUDIT=${RTK_HOOK_AUDIT:-1}
# >>> rtk token-saving aliases >>>
# Non-overriding RTK shortcuts for token-optimized agent/dev output.
# Use raw commands when exact output is required.
alias rls='rtk ls'
alias rtree='rtk tree'
alias rgrep='rtk grep'
alias rgit='rtk git'
alias rgh='rtk gh'
alias rcurl='rtk curl'
alias rwget='rtk wget'
alias rtsc='rtk tsc'
alias rpnpm='rtk pnpm'
alias rnpm='rtk npm'
alias rnpx='rtk npx'
alias rtest='rtk test'
alias rerr='rtk err'
# <<< rtk token-saving aliases <<<
# >>> headroom token-saving config >>>
# Enable Headroom AST-aware code compression for future proxy/wrap launches.
# Keep mode unset here so existing launchers can choose cache vs token explicitly.
export HEADROOM_CODE_AWARE_ENABLED=1
# <<< headroom token-saving config <<<

# ── Auto-load SSH keys from the macOS Keychain ──
# macOS Sequoia+ stopped auto-loading keys into ssh-agent at login, and our git
# remotes are HTTPS — so nothing triggers `AddKeysToAgent` and the SSH signing
# key stays out of the agent, making every signed commit re-prompt for the
# passphrase. Load keychain-stored passphrases when the agent is empty (silent:
# --apple-load-keychain never prompts and skips keys not in the Keychain).
# One-time per key first:  ssh-add --apple-use-keychain ~/.ssh/<key>
# Only load into the LOCAL launchd agent: with an inherited/forwarded
# SSH_AUTH_SOCK (SSH-in with ForwardAgent, CI runner), --apple-load-keychain
# would silently inject every Keychain-enrolled private key into a foreign
# agent that outlives this shell.
if [[ "$OSTYPE" == darwin* && -z "${SSH_CONNECTION:-}" \
      && "${SSH_AUTH_SOCK:-}" == *com.apple.launchd* ]] \
   && ! ssh-add -l &>/dev/null; then
  ssh-add --apple-load-keychain 2>/dev/null
fi

# Machine-local shell env (headroom persistent env, per-machine exports) — gitignored.
# `headroom install` and similar generators append to ~/.zshrc, which is a symlink to
# this tracked file; relocate any such block to ~/.zshrc.local so it never gets committed.
[ -f "$HOME/.zshrc.local" ] && source "$HOME/.zshrc.local"
