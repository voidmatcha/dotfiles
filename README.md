# dotfiles

macOS dev environment, automated.

Clone and run `install.sh`. It'll ask for confirmation before starting, then prompt for git name/email when it gets there.

## Quick start

```bash
git clone https://github.com/voidmatcha/dotfiles.git ~/dotfiles
cd ~/dotfiles
./install.sh
```

## What gets installed

**Homebrew + apps** — packages from `Brewfile`, including starship and the usual CLI tools.

**macOS settings** — dock autohide, Finder tweaks, keyboard repeat rates, CapsLock → Escape, three-finger drag, screenshots to `~/Screenshots`.

**Dev tools:**
- nvm + Node.js LTS, corepack (pnpm + yarn)
- pyenv + latest Python 3
- SDKMAN + Java LTS + Maven
- Playwright CLI (for coding agents)
- whisper-cpp model (~1.5GB, large-v3-turbo)
- ccusage, rtk, agent-browser

**Shell** — Oh My Zsh with zsh-autosuggestions, zsh-syntax-highlighting, zsh-completions.

**Git** — separate personal/work accounts via `includeIf`, each with its own SSH key.

**Claude Code:**
- Skills — agent-skills, clarify, code-review, e2e-skills, frontend-design, humanizer, im-not-ai, karpathy-guidelines, security-best-practices, superpowers, ui-skills, ultrawork
- Plugins — ralph-loop (iterative autonomous dev loops), [codex@openai-codex](https://github.com/openai/codex-plugin-cc) (delegate to / review with Codex from inside Claude Code; pulls in `@openai/codex` CLI)
- Hooks — skill-eval (forced-eval prompt injection per Scott Spence pattern, ~84% activation rate)
- MCP — chrome-devtools (browser control via Chrome DevTools Protocol)

**opencode:**
- Brew tap — `anomalyco/tap` (third-party tap with current versions; homebrew-core formula is stale)
- npm plugins (auto-installed via Bun on first run from `opencode.json`):
  - `oh-my-openagent@latest` — Sisyphus/Oracle/Librarian/Explore agents + category-based delegation
  - `@ex-machina/opencode-anthropic-auth@1.8.0` — Anthropic OAuth refresh
- Config — `configs/opencode/{opencode.json, oh-my-openagent.json}` symlinked to `~/.config/opencode/`
- Auth — `opencode.sh` detects missing `~/.local/share/opencode/auth.json` and prompts to run `opencode auth login`
- AGENTS.md — same canonical file as Claude Code/Cursor (symlinked to `~/.config/opencode/AGENTS.md`)

**[Hermes Agent](https://github.com/NousResearch/hermes-agent):** Nous Research's self-improving AI agent. `hermes.sh` runs the upstream one-shot installer (`curl … | bash`) — idempotent, skips if `hermes` is already on PATH. Configure with `hermes setup` after a shell reload.

**Auto-launched browser dev services (LaunchAgents):**
Both run at every login with `KeepAlive=true` (throttle 60s). Both are reached over the tailnet via `tailscale serve` (HTTPS via Tailscale's `*.ts.net` cert). code-server binds to `127.0.0.1` (kernel-level isolation). purplemux binds to `*:8022` but enforces an app-level `networkAccess: "tailscale"` filter — non-tailnet/non-loopback IPs get HTTP 403 before auth. The filter is defense-in-one; if you're on hostile wifi without NAT, also enable the macOS firewall in stealth mode.

- `com.user.purplemux` — [purplemux](https://github.com/subicura/purplemux), web-native terminal multiplexer for Claude Code
  - Installed via `npm install -g purplemux` (services.sh handles this)
  - Listens on `*:8022` (no `--bind` flag upstream); enforces `networkAccess: "tailscale"` at the app layer. Logs at `~/Library/Logs/purplemux.{out,err}.log`
  - Tailnet exposure: `tailscale serve --bg --https=443 --set-path=/ http://localhost:8022`
  - Restart: `launchctl kickstart -k gui/$(id -u)/com.user.purplemux`
- `com.user.code-server` — [code-server](https://github.com/coder/code-server), VS Code in the browser
  - Installed via Brewfile (`brew "code-server"`)
  - Reads `~/.config/code-server/config.yaml` (services.sh scaffolds with a random password and enforces `chmod 600`)
  - Binds to `127.0.0.1:8088`. Logs at `~/Library/Logs/code-server.{out,err}.log`
  - Tailnet exposure: `tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088`
  - Restart: `launchctl kickstart -k gui/$(id -u)/com.user.code-server`

**Shared agent config** — canonical `~/.agent/AGENTS.md` with shared rules, also symlinked to `~/.cursor/rules/AGENTS.md` and (after opencode setup) `~/.config/opencode/AGENTS.md`. `~/.claude/CLAUDE.md` imports it via `@AGENTS.md`.

**Dotfiles symlinks** — zshrc, gitconfig, Claude Code settings, skill-eval hook.

**SSH server** — enables macOS Remote Login with hardened sshd config (key + OTP required, no root, no password).

**Tailscale** — private mesh VPN for remote access. Each device gets a stable `100.x.x.x` IP and `*.ts.net` hostname. No port forwarding, no public exposure. Free tier covers personal use.

**OTP** — TOTP two-factor auth for SSH using google-authenticator PAM module. Requires both SSH key and authenticator app code (defense-in-depth over Tailscale).

**mosh** — mobile shell for resilient remote access. Auto-reconnects on network changes (WiFi → LTE, sleep/wake). Use with tmux for persistent sessions: `mosh yongjae@100.x.x.x -- tmux attach`

## Structure

```
dotfiles/
├── install.sh              # main entry point
├── Brewfile                # Homebrew package list
├── scripts/
│   ├── brew.sh             # Homebrew install
│   ├── macos.sh            # macOS system settings
│   ├── dev.sh              # nvm, pyenv, Java, etc.
│   ├── shell.sh            # Oh My Zsh + plugins
│   ├── git.sh              # Git config + SSH keys
│   ├── claude.sh           # Claude Code skills, plugins, tools
│   ├── lib/
│   │   └── common.sh       # shared helpers (info/warn/error/run_or_dry/link_file)
│   ├── opencode.sh         # opencode config + auth prompt
│   ├── hermes.sh           # Hermes Agent (Nous Research) installer wrapper
│   ├── services.sh         # purplemux + code-server LaunchAgent installer
│   ├── purplemux-launch.sh # LaunchAgent wrapper for purplemux (PATH + node resolution)
│   ├── code-server-launch.sh # LaunchAgent wrapper for code-server
│   ├── ssh-server.sh       # SSH server + hardened config
│   ├── tailscale.sh        # Tailscale VPN setup
│   └── otp.sh              # TOTP two-factor auth
└── configs/
    ├── .zshrc
    ├── .gitconfig
    ├── .gitconfig-personal
    ├── .gitconfig-work
    ├── AGENTS.md           # canonical agent rules (Claude + Cursor + opencode)
    ├── CLAUDE.md           # Claude Code wrapper (imports AGENTS.md)
    ├── claude-settings.json
    ├── com.user.purplemux.plist     # LaunchAgent template (sed-substituted at install)
    ├── com.user.code-server.plist   # LaunchAgent template (sed-substituted at install)
    ├── opencode/
    │   ├── opencode.json           # opencode global config + plugin list
    │   └── oh-my-openagent.json    # agents/categories with model fallbacks
    ├── rtk-config.toml
    ├── sshd_config.d/
    │   └── hardened.conf   # hardened sshd config template
    └── hooks/
        └── skill-eval.sh   # forced-eval prompt injection hook
```

## Run individual scripts

```bash
./scripts/brew.sh     # Homebrew only
./scripts/macos.sh    # macOS settings only
./scripts/dev.sh      # dev tools only
./scripts/shell.sh    # shell only
./scripts/git.sh      # Git only
```

## Dry run

Preview without making changes:

```bash
./install.sh --dry-run
```

## Separate Git accounts

`~/personal/` repos → personal account
`~/work/` repos → work account

Run `git.sh` — it prompts for names and emails, with existing values pre-filled. Press Enter to keep them.

## SSH keys

`git.sh` generates separate keys for personal and work.
Add the public keys to GitHub after:

```bash
cat ~/.ssh/id_ed25519_personal.pub  # personal
cat ~/.ssh/id_ed25519_work.pub      # work
```
