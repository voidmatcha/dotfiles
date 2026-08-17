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

# ── Claude Code: serena system-prompt override ──
# Serena's prompt-override counteracts Opus/Claude Code bias against external
# MCP tools. Bypass the function entirely with `command claude`.
if command -v claude &>/dev/null; then
  claude() {
    local -a extra
    # serena prompt override (optional — skipped if serena absent).
    if command -v serena &>/dev/null; then
      local override
      override="$(serena prompts print-cc-system-prompt-override 2>/dev/null)"
      [ -n "$override" ] && extra+=(--system-prompt="$override")
    fi
    command claude ${extra[@]+"${extra[@]}"} "$@"
  }
fi

# ── Orphaned Codex HUD panes ──
# The company overlay can start a GP Codex HUD pane. Normal exits clean up after
# themselves; a forced kill (cmux tab closed, so no `finally`) leaves the pane
# behind. Sweep those only while the HUD is disabled.
# Cost: one full pane scan per prompt (precmd), plus one `ps` per pane.
__dotfiles_cleanup_orphan_hud_panes() {
  [[ -n "${TMUX:-}" ]] || return 0
  command -v tmux >/dev/null 2>&1 || return 0
  [[ -n "${GP_CODEX_HUD_DISABLE:-}" ]] || return 0

  local pane pid args
  while IFS=$'\t' read -r pane pid; do
    [[ -n "$pane" && -n "$pid" ]] || continue
    args="$(ps -ww -o args= -p "$pid" 2>/dev/null)" || continue
    [[ "$args" == *"codex-hud"* ]] || continue
    tmux kill-pane -t "$pane" >/dev/null 2>&1 || true
  done < <(tmux list-panes -a -F '#{pane_id}\t#{pane_pid}' 2>/dev/null)
}

__dotfiles_cleanup_orphan_hud_panes >/dev/null 2>&1 || true
precmd_functions+=(__dotfiles_cleanup_orphan_hud_panes)

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
# tmux split. Keep it off by default to avoid a second HUD beside Codex's
# built-in status_line. Set GP_CODEX_HUD_DISABLE= to opt in.
export GP_CODEX_HUD_DISABLE="${GP_CODEX_HUD_DISABLE-1}"
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

# Machine-local shell env (per-machine exports, secrets) — gitignored.
# Installers sometimes append to ~/.zshrc, which is a symlink to this tracked
# file; relocate any such block to ~/.zshrc.local so it never gets committed.
[ -f "$HOME/.zshrc.local" ] && source "$HOME/.zshrc.local"
