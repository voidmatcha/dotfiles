# ── Oh My Zsh ──
export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME=""

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

# ── nvm ──
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"

# ── pyenv ──
export PYENV_ROOT="$HOME/.pyenv"
[[ -d "$PYENV_ROOT/bin" ]] && export PATH="$PYENV_ROOT/bin:$PATH"
command -v pyenv &>/dev/null && eval "$(pyenv init -)"

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

  AI agents:
    opencode serve --hostname $ip --port 4096
    opencode web --hostname $ip

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

# ── Local bin ──
export PATH="$HOME/.local/bin:$PATH"

# ── Starship ──
eval "$(starship init zsh)"
