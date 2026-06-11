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
# Owl/context-check remains advisory and optional; missing owl-rs should not
# prevent Headroom-backed entry.
export HEADROOM_MODE="${HEADROOM_MODE:-cache}"

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
alias wtcode="agent-worktrees --open"
alias wturl="agent-worktree-url"
alias wtlink="agent-worktree-link"
alias wtdeck="agent-worktree-cmux"
alias wtdeckall="agent-worktrees-cmux"

# Enable 1h prompt-cache TTL (vs 5min default) for Anthropic API
export ENABLE_PROMPT_CACHING_1H=1
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
