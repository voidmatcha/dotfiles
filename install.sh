#!/bin/bash
set -euo pipefail

# Refuse to run as root. Homebrew rejects root execution, oh-my-zsh installs
# into the wrong $HOME, and ~/Library/LaunchAgents/ ownership gets corrupted
# (the install ends up writing root-owned files into the user's tree, which
# is exactly the bug that prompted this guard). Individual steps will call
# sudo themselves where they need it.
if [ "$EUID" -eq 0 ]; then
  echo "✗ Do NOT run install.sh with sudo or as root."           >&2
  echo "  Run as your normal user: ./install.sh"                  >&2
  echo "  Individual steps (firewall, Remote Login) will sudo"   >&2
  echo "  themselves and prompt for your password as needed."    >&2
  exit 1
fi

DOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN=false
NON_INTERACTIVE=false
ASSUME_YES=false
UPGRADE=false

for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    --yes|-y) ASSUME_YES=true ;;
    --non-interactive) NON_INTERACTIVE=true; ASSUME_YES=true ;;
    --upgrade) UPGRADE=true ;;  # also bump tool versions, not just install-if-missing
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

if $DRY_RUN; then
  NON_INTERACTIVE=true
  ASSUME_YES=true
fi

export DOTFILES_DIR DRY_RUN NON_INTERACTIVE

TAG="install"
# shellcheck source=scripts/lib/common.sh
source "$DOTFILES_DIR/scripts/lib/common.sh"

if $DRY_RUN; then
  warn "=== DRY RUN MODE — no changes will be made ==="
fi

echo ""
echo "========================================="
echo "  macOS dev environment setup (dotfiles)"
echo "========================================="
echo ""
echo "The following will be installed/configured:"
echo "  1. Homebrew & apps (brew.sh + Brewfile)"
echo "  2. macOS system settings (macos.sh)"
echo "  3. Dev tools: nvm, pyenv, etc. (dev.sh)"
echo "  4. Shell — Oh My Zsh + plugins (shell.sh)"
echo "  5. Git — config + SSH keys (git.sh)"
echo "  6. dotfiles symlinks"
echo "  7. Claude Code setup (claude.sh)"
echo "  8. Codex CLI setup (codex.sh)"
echo "  9. Hermes Agent (hermes.sh)"
echo " 10. Tailscale VPN + Tailscale SSH (tailscale.sh)"
echo " 11. purplemux + code-server + agent watcher LaunchAgents (services.sh)"
echo " 12. Company overlay (only if the company/ submodule is initialized)"
echo ""

if $ASSUME_YES; then
  info "Proceeding without confirmation"
else
  read -rp "Ready to continue? (y/N) " confirm
  if [[ "$confirm" != [yY] ]]; then
    echo "Aborted."
    exit 0
  fi
fi

# ── 1. Homebrew ──
info "1/12 Installing Homebrew & apps..."
bash "$DOTFILES_DIR/scripts/brew.sh"

# ── 2. macOS settings ──
info "2/12 Applying macOS system settings..."
bash "$DOTFILES_DIR/scripts/macos.sh"

# ── 3. Dev environment ──
info "3/12 Setting up dev environment..."
bash "$DOTFILES_DIR/scripts/dev.sh"

# ── 4. Shell ──
info "4/12 Configuring shell environment..."
bash "$DOTFILES_DIR/scripts/shell.sh"

# ── 5. Git ──
info "5/12 Configuring Git..."
bash "$DOTFILES_DIR/scripts/git.sh"

# Pre-push validation hook: lefthook runs scripts/verify.sh before every push so
# broken changes are caught locally instead of failing CI (see lefthook.yml).
if command -v lefthook >/dev/null 2>&1; then
  ( cd "$DOTFILES_DIR" && lefthook install >/dev/null 2>&1 ) && info "lefthook pre-push hook installed"
else
  warn "lefthook not found; skipping pre-push hook (install via Brewfile)"
fi

# ── 6. Symlinks ──
info "6/12 Creating dotfiles symlinks..."

link_file "$DOTFILES_DIR/configs/.zshrc"              "$HOME/.zshrc"
link_file "$DOTFILES_DIR/configs/.tmux.conf"          "$HOME/.tmux.conf"
link_file "$DOTFILES_DIR/configs/.gitconfig"           "$HOME/.gitconfig"
link_file "$DOTFILES_DIR/configs/.gitconfig-personal"  "$HOME/.gitconfig-personal"
link_file "$DOTFILES_DIR/configs/.gitconfig-work"      "$HOME/.gitconfig-work"
link_file "$DOTFILES_DIR/configs/.gitignore_global"    "$HOME/.gitignore_global"
ensure_dir "$HOME/.local/bin"
link_file "$DOTFILES_DIR/scripts/auth.sh"              "$HOME/.local/bin/dotfiles-auth"
ensure_dir "$HOME/.local/share/zsh/site-functions"
link_file "$DOTFILES_DIR/configs/zsh-completions/_dotfiles-auth" \
  "$HOME/.local/share/zsh/site-functions/_dotfiles-auth"

# shared agent config (canonical)
ensure_dir "$HOME/.agent"
link_file "$DOTFILES_DIR/configs/AGENTS.md" "$HOME/.agent/AGENTS.md"

# Claude Code
# NOTE: MCP servers are NOT registered via symlinking a file. Claude Code stores
# user-scope MCP entries in ~/.claude.json (managed via `claude mcp add`), not in
# ~/.claude/.mcp.json. Registration is handled by scripts/claude.sh which reads
# configs/mcp.json (single source of truth) and runs `claude mcp add-json`.
ensure_dir "$HOME/.claude/hooks" "$HOME/.claude/plugins" "$HOME/.claude/commands" "$HOME/.claude/agents"
link_file "$DOTFILES_DIR/configs/claude-settings.json" "$HOME/.claude/settings.json"
link_file "$DOTFILES_DIR/configs/CLAUDE.md"            "$HOME/.claude/CLAUDE.md"
link_file "$DOTFILES_DIR/configs/RTK.md"               "$HOME/.claude/RTK.md"
link_file "$DOTFILES_DIR/configs/hooks/pretool-guard.sh" "$HOME/.claude/hooks/pretool-guard.sh"
link_file "$DOTFILES_DIR/configs/hooks/skill-md-edit-warn.sh" "$HOME/.claude/hooks/skill-md-edit-warn.sh"
link_file "$DOTFILES_DIR/configs/hooks/work-scope-guard.sh" "$HOME/.claude/hooks/work-scope-guard.sh"
link_file "$DOTFILES_DIR/configs/hooks/context-check.sh" "$HOME/.claude/hooks/context-check.sh"
link_file "$DOTFILES_DIR/configs/llmwiki/hook-session-start.sh" "$HOME/.claude/hooks/llmwiki-session-start.sh"
link_file "$DOTFILES_DIR/configs/llmwiki/hook-user-prompt.sh" "$HOME/.claude/hooks/llmwiki-user-prompt.sh"

# llmwiki 첫 부트스트랩. compile 은 config.toml 없이 돌기를 거부한다 - 설정이
# 없으면 blocklist 와 mapping 이 비어 Documents 나 tmp 같은 프로젝트 페이지가
# 생기기 때문이다. 그 거부가 옳지만, 아무도 init 을 부르지 않으면 새 머신은
# 야간 작업이 매일 같은 오류로 멈춘 채 방치된다.
#
# 조건은 config.toml 의 존재다. 볼트가 비었는지로 판단하면 사용자가 페이지를
# 지웠을 때 설정까지 다시 만들어 덮어쓴다.
_llmwiki_home="${LLMWIKI_HOME:-$HOME/.local/share/llmwiki}"
if [ ! -f "$_llmwiki_home/config.toml" ]; then
  if $DRY_RUN; then
    info "[dry-run] python3 -m scripts.llmwiki init (첫 설치)"
  # 조건을 판정한 경로와 init 이 실제로 쓸 경로가 같아야 한다. 내보내지
  # 않으면 셸이 본 값과 파이썬이 본 값이 갈라져, 이미 설정된 볼트에 대고
  # "부트스트랩했다"고 보고할 수 있다.
  # LLMWIKI_VAULT 를 벗겨낸다. 설치하는 셸에 그것이 있으면 init 은 env 를
  # 따라 그 경로에 볼트를 만들고 seed config 에는 vault = "" 가 남는다.
  # 훅과 launchd 는 셸 env 를 보지 못하므로 첫날부터 볼트가 둘로 갈라지고,
  # 그 상태를 잡을 doctor 검사조차 launchd 아래에서는 env 를 못 봐서
  # 구조적으로 발동하지 않는다.
  elif (cd "$DOTFILES_DIR" && unset LLMWIKI_VAULT && LLMWIKI_HOME="$_llmwiki_home" \
        python3 -m scripts.llmwiki init >/dev/null 2>&1); then
    info "llmwiki bootstrapped -> $_llmwiki_home"
  else
    # init 은 비어 있지 않은 볼트를 거부한다. 복원한 볼트에 새 home 을 붙인
    # 경우가 그렇고, 그때는 매 설치마다 같은 경고가 나면서 야간 작업은
    # 영원히 설정 없음으로 멈춘다. 무엇을 해야 하는지 말해준다.
    # cd 와 unset 을 함께 적는다. 저장소 밖에서는 모듈을 못 찾고,
    # LLMWIKI_VAULT 가 남은 셸에서 실행하면 방금 막은 볼트 분리를 그대로
    # 다시 만든다.
    warn "llmwiki init failed - the nightly job will stop at the missing config."
    warn "  if the vault already exists, seed the config without touching it:"
    warn "    (cd \"$DOTFILES_DIR\" && unset LLMWIKI_VAULT && python3 -m scripts.llmwiki init --force)"
  fi
fi

# llmwiki 야간 작업. 훅은 세션 중에만 기록한다. 적재/컴파일/스냅샷은 아무도
# 부르지 않으면 영원히 돌지 않는다 - 실측으로 볼트가 14시간 밀린 적이 있다.
ensure_dir "$HOME/Library/LaunchAgents"
ensure_dir "$HOME/Library/Logs"
render_file "$DOTFILES_DIR/configs/llmwiki/com.yongjae.llmwiki.plist" \
  "$HOME/Library/LaunchAgents/com.yongjae.llmwiki.plist"
render_file "$DOTFILES_DIR/configs/llmwiki/com.yongjae.llmwiki-web.plist" \
  "$HOME/Library/LaunchAgents/com.yongjae.llmwiki-web.plist"

reload_launch_agent() {
  local label="$1" plist="$2"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  if launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; then
    return 0
  fi

  # bootout can return before launchd has fully released the old label. One
  # bounded retry avoids leaving a previously healthy service stopped.
  sleep 1
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  if launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; then
    info "$label loaded on retry"
    return 0
  fi
  warn "could not load $label"
  return 1
}

if $DRY_RUN; then
  info "[dry-run] launchctl bootstrap com.yongjae.llmwiki, com.yongjae.llmwiki-web"
elif command -v launchctl >/dev/null 2>&1; then
  for _job in com.yongjae.llmwiki com.yongjae.llmwiki-web; do
    reload_launch_agent "$_job" "$HOME/Library/LaunchAgents/$_job.plist" || true
  done
fi
# 주간 점검. 검사가 있어도 아무도 돌리지 않으면 두 달이 지나간다.
render_file "$DOTFILES_DIR/configs/launchd/com.yongjae.dotfiles-doctor.plist" \
  "$HOME/Library/LaunchAgents/com.yongjae.dotfiles-doctor.plist"
if $DRY_RUN; then
  info "[dry-run] launchctl bootstrap com.yongjae.dotfiles-doctor"
elif command -v launchctl >/dev/null 2>&1; then
  reload_launch_agent "com.yongjae.dotfiles-doctor" \
    "$HOME/Library/LaunchAgents/com.yongjae.dotfiles-doctor.plist" || true
fi

# 읽기 전용 뷰어를 tailnet 에만 연다. Funnel(공개)은 쓰지 않는다.
# Publishing is opt-in, the same gate scripts/services.sh uses. The vault holds
# personal notes, so reaching the tailnet must be a decision, not a side effect
# of running the installer.
if $DRY_RUN; then
  info "[dry-run] llmwiki viewer publish opt-in is ENABLE_TAILSCALE_SERVE=1"
  info "[dry-run] tailscale serve --bg --https=8391 http://127.0.0.1:8391"
elif [ "${ENABLE_TAILSCALE_SERVE:-0}" = "1" ] && command -v tailscale >/dev/null 2>&1; then
  tailscale serve status 2>/dev/null | grep -q ":8391" \
    || tailscale serve --bg --https=8391 http://127.0.0.1:8391 >/dev/null 2>&1 \
    || warn "could not publish llmwiki viewer on the tailnet"
fi
link_file "$DOTFILES_DIR/configs/agents/scout.md"     "$HOME/.claude/agents/scout.md"
link_file "$DOTFILES_DIR/configs/agents/critic.md"    "$HOME/.claude/agents/critic.md"
link_file "$DOTFILES_DIR/configs/agents/debugger.md"  "$HOME/.claude/agents/debugger.md"
link_file "$DOTFILES_DIR/configs/agents/test-engineer.md" "$HOME/.claude/agents/test-engineer.md"
link_file "$DOTFILES_DIR/configs/agents/security-reviewer.md" "$HOME/.claude/agents/security-reviewer.md"
link_file "$DOTFILES_DIR/configs/agents/git-master.md" "$HOME/.claude/agents/git-master.md"

# Codex CLI
ensure_dir "$HOME/.codex"
# Codex config is a mutable local file. scripts/codex.sh copies the portable
# template and preserves machine-local project/plugin/hook state; do not symlink
# it or Codex runtime writes can dirty this repo.

RTK_CONFIG_DIR="$HOME/Library/Application Support/rtk"
ensure_dir "$RTK_CONFIG_DIR"
link_file "$DOTFILES_DIR/configs/rtk-config.toml"     "$RTK_CONFIG_DIR/config.toml"

# ── 7. Claude Code ──
info "7/12 Setting up Claude Code..."
bash "$DOTFILES_DIR/scripts/claude.sh"

# ── 8. Codex CLI ──
info "8/12 Setting up Codex CLI..."
bash "$DOTFILES_DIR/scripts/codex.sh"

# ── 9. Hermes Agent ──
info "9/12 Setting up Hermes Agent..."
bash "$DOTFILES_DIR/scripts/hermes.sh"

# ── 10. Tailscale + Tailscale SSH ──
info "10/12 Setting up Tailscale (incl. Tailscale SSH)..."
bash "$DOTFILES_DIR/scripts/tailscale.sh"

# ── 11. purplemux + code-server + agent watcher services ──
info "11/12 Configuring purplemux + code-server + agent watcher services..."
bash "$DOTFILES_DIR/scripts/services.sh"

# ── 회사용 overlay (옵션, git submodule) ──
# company/ 는 git submodule로 별도의 사내 git 저장소에 호스팅된다.
# 새 머신: git clone --recurse-submodules ... 또는 git submodule update --init
info "12/12 Applying company overlay (if available)..."

if [ "${SKIP_COMPANY_OVERLAY:-false}" = "true" ]; then
  warn "Company overlay explicitly skipped because its submodule was not refreshed safely."
elif [ -x "$DOTFILES_DIR/company/install.sh" ]; then
  if ! company_overlay_current "$DOTFILES_DIR"; then
    error "Refusing stale, dirty, or unverifiable company overlay: company/ must be clean and match the parent gitlink."
    error "Repair with: git -C $DOTFILES_DIR submodule update --init --recursive"
    exit 1
  fi
  echo ""
  info "Detected company/install.sh — running company overlay..."
  bash "$DOTFILES_DIR/company/install.sh"
elif [ -f "$HOME/.company.secrets.env" ]; then
  echo ""
  # shellcheck disable=SC2088  # ~/.company.secrets.env is display text, not a path to expand
  warn "~/.company.secrets.env present but company/ submodule is not initialized."
  warn "Run: git -C $DOTFILES_DIR submodule update --init"
  warn "(Requires SSH access to the internal git host — see company/README.md)"
fi

echo ""
info "Done."
info "Restart your terminal or run 'source ~/.zshrc'."

# ── Manual one-time login flows (interactive — surface one entry point) ──
echo ""
warn "=== One-time browser sessions ==="
warn "  dotfiles-auth setup social   # LinkedIn, X/Twitter, Reddit"
warn "Sessions remain in each provider's local browser profile; they are not copied into shell variables."
info "  yt-dlp needs no login; Jina Reader and defuddle need no login by default."
info ""
info "=== Unified authentication ==="
info "  dotfiles-auth status          # no secret values are read or printed"
info "  dotfiles-auth catalog         # credential owner + route map, no values"
info "  dotfiles-auth setup all       # OAuth flows + official token pages"
info "  dotfiles-auth setup personal  # browser OAuth for gh/Codex/Figma/Atlassian"
info "  dotfiles-auth setup social    # provider-owned LinkedIn/X/Reddit sessions"
info "  dotfiles-auth set all         # personal + work-read tokens -> Keychain"
info "  dotfiles-auth register sentry SENTRY_AUTH_TOKEN work-ro  # any CLI/SDK/MCP token"
info "  dotfiles-auth profile set work-ro  # repository-local routing"
info "  GitHub Operations on the public dotfiles use 'gh' CLI directly."
info "  The company overlay (if active) adds GitHub MCP servers — see company/AGENTS-company.md."
info ""
info "=== gh CLI authentication ==="
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  info "  gh: github.com authenticated ✓"
else
  info "  See step 2 in the 'REQUIRED MANUAL STEPS' block printed by scripts/git.sh"
  info "  (includes correct scopes for ssh-key add + ssh signing key)."
fi
