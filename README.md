# dotfiles

macOS dev environment, automated.

Clone and run `install.sh`. It'll ask for confirmation before starting, then prompt for git name/email when it gets there.

## Quick start

```bash
git clone https://github.com/dididy/dotfiles.git ~/dotfiles
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
- Plugin — ralph-loop (iterative autonomous dev loops)
- Hooks — skill-eval (forced-eval prompt injection per Scott Spence pattern, ~84% activation rate)
- MCP — chrome-devtools (browser control via Chrome DevTools Protocol)

**opencode:**
- Brew tap — `anomalyco/tap` (third-party tap with current versions; homebrew-core formula is stale)
- npm plugins (auto-installed via Bun on first run from `opencode.json`):
  - `oh-my-openagent@latest` — Sisyphus/Oracle/Librarian/Explore agents + category-based delegation
  - `@ex-machina/opencode-anthropic-auth@1.7.5` — Anthropic OAuth refresh
- Local plugins (in `configs/opencode/plugins/`, loaded as `.ts` directly via Bun):
  - `discord-notify.ts` — posts one Discord embed on `session.idle`. Title `✅ [project] title`, description with the last assistant message (truncated), URL deep-linking into the LaunchAgent's tailnet-only `opencode web` (`<server>/<base64(directory)>/session/<id>` — never creates a public share).
- Config — `configs/opencode/{opencode.json, oh-my-openagent.json}` symlinked to `~/.config/opencode/`
- Auth — `opencode.sh` detects missing `~/.local/share/opencode/auth.json` and prompts to run `opencode auth login`
- AGENTS.md — same canonical file as Claude Code/Cursor (symlinked to `~/.config/opencode/AGENTS.md`)

**opencode web auto-start (LaunchAgent):**
- `com.user.opencode-web` runs `opencode web` at every login (`KeepAlive=true`, throttle 60s)
- Wrapper waits up to 30s for Tailscale, binds to `100.x.x.x:4096` (falls back to `127.0.0.1:4096` if tailnet down)
- Logs at `~/Library/Logs/opencode-web.{out,err}.log`
- Restart after editing secrets: `launchctl kickstart -k gui/$(id -u)/com.user.opencode-web`

**Discord notify setup:**
1. In your Discord server, open a channel → Integrations → Webhooks → New Webhook → copy the URL.
2. Edit `~/.opencode-secrets.env` (scaffolded by `opencode.sh` with chmod 600 on first run) and uncomment the webhook line:
   ```bash
   DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
   ```
3. Restart the LaunchAgent so opencode picks up the new env: `launchctl kickstart -k gui/$(id -u)/com.user.opencode-web`
4. Trigger any opencode session through the LaunchAgent's web UI; you should get a Discord notification when it goes idle.

**Discord notify secrets / privacy:**
- `~/.opencode-secrets.env` is gitignored and chmod 600. Wrapper refuses to source it if perms are not 600 or owner is not the current user (exits 78).
- The plugin POSTs to Discord: session title, last assistant message (truncated to 600 chars), and a deep link to the LaunchAgent's `opencode web` URL on the Tailscale IP. **No public share is created** — the URL only resolves on your tailnet.
- Discord still receives the session title + last response, so pin the webhook to a private channel.

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
│   ├── opencode.sh         # opencode config + plugins + LaunchAgent + auth prompt
│   ├── opencode-web-launch.sh  # LaunchAgent wrapper (waits for tailscale, sources secrets)
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
    ├── com.user.opencode-web.plist  # LaunchAgent template (sed-substituted at install)
    ├── opencode/
    │   ├── opencode.json           # opencode global config + plugin list
    │   ├── oh-my-openagent.json    # agents/categories with model fallbacks
    │   └── plugins/
    │       └── discord-notify.ts   # session.idle → Discord embed with tailnet-only opencode web deep link
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
