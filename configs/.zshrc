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

# ── Claude Code: serena system-prompt override (Opus built-in-tool bias workaround) ──
# Opus + CC's large built-in tool descriptions create strong bias
# against external MCP tools. Serena's prompt-override counteracts this so
# Serena's semantic tools actually get used. Falls back to plain `claude` if
# serena is not installed. See https://github.com/oraios/serena
if command -v claude &>/dev/null; then
  claude() {
    local -a extra
    # serena prompt override (optional — skipped if serena absent).
    if command -v serena &>/dev/null; then
      local override
      override="$(serena prompts print-cc-system-prompt-override 2>/dev/null)"
      [ -n "$override" ] && extra+=(--system-prompt="$override")
    fi
    # ultracode (xhigh effort + standing dynamic-workflow orchestration) is
    # session-scoped and NOT read from settings.json, so opt every launch into
    # it here. effortLevel:xhigh lives in settings.json; this adds the standing
    # workflow orchestration on top. Disable per-session with CLAUDE_ULTRACODE=0.
    # CC honors only the FIRST --settings flag (later ones silently dropped),
    # so if the caller already passes one (e.g. cmux injects its hooks via
    # --settings), merge ultracode INTO it instead of adding a second flag —
    # otherwise we'd shadow the caller's settings. On merge failure, leave the
    # caller's args untouched (ultracode skipped, launch never broken).
    local -a args
    args=("$@")
    if [ "${CLAUDE_ULTRACODE:-1}" != "0" ]; then
      local i merged=0 val
      for (( i = 1; i <= $#args; i++ )); do
        case "${args[i]}" in
          --settings)
            (( i < $#args )) || break
            val="$(_claude_ultracode_merge "${args[i+1]}")" && { args[i+1]="$val"; }
            merged=1
            break ;;
          --settings=*)
            val="$(_claude_ultracode_merge "${args[i]#--settings=}")" && { args[i]="--settings=$val"; }
            merged=1
            break ;;
        esac
      done
      (( merged )) || extra+=(--settings '{"ultracode":true}')
    fi
    command claude ${extra[@]+"${extra[@]}"} "${args[@]}"
  }
  # Merge {"ultracode":true} into a --settings value (JSON string or file path).
  # Prints merged JSON on success; exits non-zero (prints nothing) on failure.
  _claude_ultracode_merge() {
    python3 -c '
import json, os, sys
v = sys.argv[1]
try:
    d = json.loads(v) if v.lstrip().startswith("{") else json.load(open(os.path.expanduser(v)))
    if not isinstance(d, dict):
        sys.exit(1)
except Exception:
    sys.exit(1)
d.setdefault("ultracode", True)
print(json.dumps(d))
' "$1" 2>/dev/null
  }
fi

# ── omx (oh-my-codex): default launch flags ──
# Codex-side analog of the claude() wrapper above: every interactive launch
# gets --direct (no OMX tmux/HUD management), --xhigh (reasoning effort), and
# --madmax (bypass Codex approvals/sandbox — intentional, mirrors Claude's
# auto permission mode). Subcommands (setup/doctor/exec/…) are left untouched;
# explicit flags passed later win (last-flag-wins per omx launch policy).
# Disable per-session with OMX_DEFAULT_FLAGS=0.
if command -v omx &>/dev/null; then
  omx() {
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
