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
- Skills — humanizer, e2e-skills, karpathy-guidelines, superpowers, agent-skills, frontend-design, security-best-practices, code-review, ultrawork, clarify
- Plugin — ralph-loop (iterative autonomous dev loops)
- Tool — ralph-kage-bunshin (parallel multi-agent orchestration via tmux)
- Hooks — skill-eval (forced skill activation), hone-english (grammar feedback + vault logging)
- MCP — chrome-devtools (browser control via Chrome DevTools Protocol)

**Shared agent config** — `~/.agent/AGENT.md` with shared rules, symlinked to both `~/.claude/` (via `@` import) and `~/.cursor/rules/`.

**Dotfiles symlinks** — zshrc, gitconfig, starship.toml, Claude Code settings, skill-eval hook.

**hone-english** — cloned separately to `~/Documents/hone-english` (Claude Code hooks for English learning).

**SSH server** — enables macOS Remote Login with hardened sshd config (key + OTP required, no root, no password).

**DuckDNS** — dynamic DNS via LaunchAgent, updates your public IP to `*.duckdns.org` every 5 minutes.

**OTP** — TOTP two-factor auth for SSH using google-authenticator PAM module. Requires both SSH key and authenticator app code.

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
│   ├── ssh-server.sh       # SSH server + hardened config
│   ├── ddns.sh             # DuckDNS dynamic DNS
│   └── otp.sh              # TOTP two-factor auth
└── configs/
    ├── .zshrc
    ├── .gitconfig
    ├── .gitconfig-personal
    ├── .gitconfig-work
    ├── AGENT.md            # shared agent rules (Claude + Cursor)
    ├── CLAUDE.md           # Claude Code instructions (imports AGENT.md)
    ├── claude-settings.json
    ├── rtk-config.toml
    ├── starship.toml
    ├── com.user.duckdns.plist  # DuckDNS LaunchAgent template
    ├── sshd_config.d/
    │   └── hardened.conf   # hardened sshd config template
    └── hooks/
        └── skill-eval.sh   # forced skill activation hook
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
