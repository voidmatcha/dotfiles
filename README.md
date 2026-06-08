# dotfiles

My opinionated macOS dev setup. Three goals: AI-assisted by default (Claude Code, hermes-agent, codex CLI side-by-side), remote access via Tailscale (private mesh, no public ports) with both OpenSSH and Tailscale SSH enabled side-by-side, and reproducible (idempotent scripts, `--dry-run`, CI-checked with shellcheck + `bash -n` + Brewfile validation + bats).

Run `bootstrap.sh` (one curl line on a fresh Mac) or clone + `./install.sh`
manually. Either way it asks for confirmation before doing anything, then
prompts for git name/email when it gets to that step.

## Quick start (fresh machine, one-shot)

```bash
curl -fsSL https://raw.githubusercontent.com/voidmatcha/dotfiles/main/bootstrap.sh | bash
```

`bootstrap.sh` installs Xcode Command Line Tools if `git` is missing, clones
this repo (with submodules) into `~/dotfiles`, and hands off to `./install.sh`.
The `--recurse-submodules` step pulls the optional `company/` overlay if you
have access to the internal git host; without access the submodule clone
fails silently and `install.sh` proceeds normally.

Pass-through args work too:

```bash
curl -fsSL https://raw.githubusercontent.com/voidmatcha/dotfiles/main/bootstrap.sh | bash -s -- --dry-run
```

## Quick start (already cloned)

```bash
cd ~/dotfiles
./install.sh
```

## What gets installed

**Homebrew + apps** — packages from `Brewfile`, including the usual CLI tools (ripgrep/fd/bat/eza/fzf/zoxide/atuin/direnv/jq/delta/tmux) plus `bats-core` for shell-script tests, `uv` (Python tool installer used by serena), `gettext` (envsubst, used by company overlay), `git-filter-repo` (surgical history rewrites), and `docker` CLI (no Docker Desktop — pair with Rancher Desktop on hosts with licensing restrictions).

**macOS settings** — dock autohide, Finder tweaks, keyboard repeat rates, CapsLock → Escape, three-finger drag, screenshots to `~/Screenshots`.

**Dev tools:**
- nvm + Node.js LTS, corepack (pnpm + yarn)
- pyenv + latest Python 3
- SDKMAN + Java LTS + Maven
- Playwright CLI (for coding agents)
- whisper-cpp model (~1.5GB, large-v3-turbo)
- ccusage, agentsview, rtk, agent-browser
- defuddle — free local web extraction tool for LLM-friendly Markdown
- [serena](https://github.com/oraios/serena) — MCP server for semantic code navigation + **editing** (LSP-backed). Installed via `uv tool install`, registered in `configs/mcp.json` with `--context claude-code --project-from-cwd`. `.zshrc` wraps `claude` to inject serena's system-prompt-override (counters Opus's bias toward built-in tools)
- [codegraph](https://github.com/colbymchenry/codegraph) — read-only MCP server for **exploring** large codebases via a pre-indexed knowledge graph (tree-sitter + SQLite, watcher auto-syncs on save). Installed via `npm install -g @colbymchenry/codegraph`. Complementary to serena: codegraph wins on "how does X reach Y" / architecture / framework-route mapping / iOS+RN cross-language bridges; serena wins on symbol-level edits and refactors. Run `codegraph init -i` once per project. Personal user-scope only — not in the NAVER MCP catalog, so excluded from company project-scope (`~/work/.mcp.json`).
- [graphify](https://github.com/safishamsi/graphify) — Claude Code skill (`/graphify`) that turns any folder into a queryable knowledge graph. For pure code, codegraph is more specialized; reach for graphify on mixed content (PDFs, docs, papers). Installed via `pip install --user graphifyy && graphify install`
- [agentsview](https://github.com/kenn-io/agentsview) — local-first Claude/Codex session browser and usage analytics dashboard. Installed via Homebrew cask (`brew install --cask agentsview`); CLI one-liners include `agentsview serve`, `agentsview usage daily --all --json`, `agentsview stats --format json`, and `agentsview session usage <id> --format json`.
- [wrangler](https://developers.cloudflare.com/workers/wrangler/) — Cloudflare Workers/Pages/R2/D1 CLI
- Social / web read CLIs (subset of what [agent-reach](https://github.com/Panniantong/Agent-Reach) bundles, installed directly to keep the dependency surface small):
  - `yt-dlp` — YouTube/Bilibili/1800+ sites, metadata + subtitles, no auth
  - `twitter` ([public-clis/twitter-cli](https://github.com/public-clis/twitter-cli), via pipx) — X/Twitter read/search/timeline/profile; auto-reads browser cookies (Chrome/Firefox), no API key required — matches Agent-Reach upstream
  - `rdt` (rdt-cli, via pipx) — Reddit search/read; `rdt login` once (Reddit requires auth since 2024)
  - `feedparser` (Python lib) — RSS/Atom feeds (blog/YouTube channel/GitHub releases/Hacker News etc.)
  - For any other URL, `curl https://r.jina.ai/<URL>` returns clean Markdown (Jina Reader, no install)
  - See `configs/AGENTS.md` for exact one-liners agents should call.
- MCP servers wired up by `configs/mcp.json` (registered via `claude mcp add-json --scope user`):
  - **chrome-devtools** — browser control
  - **serena** — semantic code intelligence (LSP edit/refactor)
  - **codegraph** — pre-indexed code graph (read-only; exploration / trace / architecture)
  - **linkedin** (`linkedin-scraper-mcp` via `uvx`) — LinkedIn profiles/companies/jobs (browser auth on first call). Excluded on internal NAVER machines — not yet security-reviewed.
  - **exa** — semantic web search + `web_fetch_exa` URL reader. Connects to Exa's provider-hosted endpoint (`https://mcp.exa.ai/mcp`) anonymously — no API key needed for free-plan usage. Add `x-api-key` header (key from https://dashboard.exa.ai/) only if you hit the rate limit. On company overlay machines it is not hard-pruned because it is provider-official, but it remains user-scope only and must never receive internal data.
  - **context7** — up-to-date library/framework docs lookup. Connects to Context7's hosted endpoint (`https://mcp.context7.com/mcp`) anonymously for basic usage. The company overlay sources `CONTEXT7_API_KEY` from `~/.company.secrets.env` to lift rate limits when working under `~/work/`.
  - GitHub Operations on the public dotfiles use the `gh` CLI directly. The company overlay (if configured) can add a `github-enterprise` MCP for the corporate GitHub Enterprise host — see `company/configs/AGENTS-company.md`.

**Shell** — Oh My Zsh with zsh-autosuggestions, zsh-syntax-highlighting, zsh-completions.

**Git** — separate personal/work accounts via `includeIf` with **remote-URL-based** routing (see "Separate Git accounts" below). Commits and tags are SSH-signed by default — register the public key as a Signing Key on GitHub to get a verified badge. A global `~/.gitignore_global` (symlink to `configs/.gitignore_global`) catches `.DS_Store`, editor leftovers, and local `.env*` files while leaving shared `.envrc` files trackable for direnv.

**Claude Code:**
- Install — native build via `scripts/claude.sh`, which downloads the official `claude.ai/install.sh` (to `~/.local`) and runs it from disk (no curl-pipe-bash); thereafter it self-updates with `claude update`. Deliberately **not** Homebrew — the cask lags upstream and gets shadowed by `~/.local/bin` on PATH, so a brew-installed `claude` is never the one that actually runs.
- Skills — agent-skills, ai-slop-cleaner, clarify, code-review, doc-coauthoring, e2e-skills, frontend-design, humanizer, im-not-ai, internal-comms, karpathy-guidelines, mcp-builder, obsidian-skills, project-session-manager (`/oh-my-claudecode:psm`), security-best-practices, skill-creator, ui-clone-skills, webapp-testing, plus repo-local skills (`dotfiles-verify`, `agent-usage-audit`, `code-intel-doctor`, `work-scope-guard`, `context-check`, `source-provenance`, `cmux-handoff-runner`, `handover`, `agent-reap`) exposed from `plugins/local-skills/skills/` via `scripts/skills.sh`
- Local agents — scout, critic, debugger, test-engineer, security-reviewer, and git-master are symlinked from `configs/agents/` into `~/.claude/agents/` so core review/debug/test/git lanes work even before optional plugin marketplaces are available.
- Plugins (enabled by default) — `local-skills@dotfiles-local` (this repo as a local Claude skill plugin; Codex gets the same repo-local skills through `scripts/skills.sh codex` symlinks), [claude-hud@claude-hud](https://github.com/jarrodwatts/claude-hud) (context/tool/agent/todo statusline; run `/claude-hud:setup` once; personal machines only), [skills-janitor@skills-janitor](https://github.com/khendzel/skills-janitor) (skill inventory, duplicates, token value, cleanup), [codex@openai-codex](https://github.com/openai/codex-plugin-cc) (delegate to / review with the local Codex CLI from inside Claude Code), security-guidance, superpowers, claude-md-management (`/claude-md-management:revise-claude-md` + `claude-md-improver` audit skill), hookify, session-wrap, [claude-mem@thedotmack](https://github.com/thedotmack/claude-mem) (persistent memory + cross-session search), plus comprehensive-review and documentation-generation from the [wshobson/agents](https://github.com/wshobson/agents) marketplace. Plugin slash command names follow each plugin's manifest: many use `/<plugin-name>:<command>`; standalone skills (`/graphify`, etc.) don't take the prefix.
- Plugins (parked — installed/cached but `enabledPlugins: false`; largely superseded by native Claude Code features such as workflows/ultracode, `/simplify`, `/code-review`, `/security-review`, and worktrees; revive with one settings flip) — ralph-loop, [autoresearch@autoresearch](https://github.com/uditgoenka/autoresearch), [review-loop@hamel-review](https://github.com/hamelsmu/claude-review-loop) (`REVIEW_LOOP_CODEX_FLAGS="--sandbox workspace-write"` stays set so a revival never inherits the plugin's dangerous default), rust-analyzer-lsp, fakechat, vercel, session-report, and the remaining [wshobson/agents](https://github.com/wshobson/agents) packs (javascript-typescript, python-development, frontend-mobile-development, security-scanning, unit-testing, tdd-workflows, git-pr-workflows, error-debugging, ui-design, accessibility-compliance, content-marketing, seo-*).
- Hooks — `rtk hook claude` (in-place PreToolUse hook registered via `rtk init --global`; compresses Bash output 60–90%), pretool-guard (structured PreToolUse deny for risky Bash), skill-md-edit-warn (PostToolUse reminder after editing `SKILL.md`), work-scope-guard (SessionStart advisory when cwd is under configured work roots), context-check (UserPromptSubmit advisory for continue/compact/clear/handover pressure; never auto-clears), plus security-guidance plugin hooks (edit/stop security review; the Stop-hook code-review pass is disabled via `ENABLE_CODE_SECURITY_REVIEW=0`). Hooks from parked plugins (autoresearch, review-loop) stay dormant while those plugins are disabled.
- MCP — chrome-devtools (browser control via Chrome DevTools Protocol), serena (semantic code intelligence, LSP edit/refactor), codegraph (read-only pre-indexed code graph for exploration), context7 (version-aware docs lookup). Defined in `configs/mcp.json`; `scripts/claude.sh` registers each entry via `claude mcp add-json --scope user` (writes to `~/.claude.json`, not the older `.mcp.json` symlink path), while Claude settings pin the approved managed servers.
- Codex CLI — first-class `scripts/codex.sh` setup owns `@openai/codex` install/auth, installs the official cmux Codex skill plus repo-local skills into `~/.codex/skills/` (including `$context-check` for continue/compact/clear/handover advice), and copies the portable `configs/codex/config.toml` template to `~/.codex/config.toml` so Codex's machine-local trust/runtime entries don't dirty the repo.
- Token saving — settings calibrated against [spilist's checklist gist](https://gist.github.com/spilist/c468cbf1ed0ffc91100f813aabdcd520) (verified against official docs). Claude Code: `includeGitInstructions: false` drops the built-in git workflow instructions + git status snapshot from the system prompt. `autoInstallIdeExtension: false` keeps Claude Code as a pure terminal tool — no auto-install of VS Code/JetBrains extensions. Codex: `web_search = "disabled"` drops the web_search tool definition (re-enable per-invocation with `codex --search`). `[features].apps = false` drops ChatGPT-connector tool definitions.

**Codex CLI:**
- CLI — `scripts/codex.sh` installs `@openai/codex` with npm when `codex` is missing; upstream also supports `brew install --cask codex`
- Config — `configs/codex/config.toml` is copied to `~/.codex/config.toml`; it sets OpenAI `gpt-5.5`, `approval_policy = "on-request"`, `sandbox_mode = "workspace-write"`, `web_search = "disabled"`, `[features] apps = false`, `[features] goals = true`, and four `[mcp_servers.*]` entries: `chrome-devtools`, `serena` (LSP code intelligence), `codegraph` (read-only code graph), `context7` (current docs lookup)
- Skills — `scripts/codex.sh` installs the cmux skill from `manaflow-ai/cmux` (`skills/cmux`) into `~/.codex/skills/cmux` and calls `scripts/skills.sh codex` to symlink repo-local skills into `~/.codex/skills/`.
- Profile — `codex --profile yolo` is available as an explicit opt-in profile (`approval_policy = "never"`, `sandbox_mode = "danger-full-access"`); don't use it outside an isolated environment
- Auth — `codex.sh` checks `codex login status`; run `codex login` for ChatGPT sign-in, `codex login --device-auth` for a headless device-code flow, or `printenv OPENAI_API_KEY | codex login --with-api-key` for API-key auth

**[Hermes Agent](https://github.com/NousResearch/hermes-agent):** Nous Research's self-improving AI agent. `hermes.sh` runs the upstream one-shot installer (`curl … | bash`) — idempotent, skips if `hermes` is already on PATH. Configure with `hermes setup` after a shell reload.

**tmux** — minimal `~/.tmux.conf` (symlinked from `configs/.tmux.conf`): `C-Space` prefix, mouse on, vi-mode copy, `|`/`-` splits that keep CWD, 100k scrollback, true-color.

**Auto-launched browser dev services (LaunchAgents):**
Installed services run at every login with `KeepAlive=true` (throttle 60s); `services.sh` skips loading LaunchAgents when dependencies are missing. Both services are reached over the tailnet via `tailscale serve` (HTTPS via Tailscale's `*.ts.net` cert; configured automatically by `services.sh`). code-server binds to `127.0.0.1` (kernel-level isolation). purplemux binds to `*:8022`, so this setup relies on Tailscale Serve plus the macOS firewall rather than an app-level tailnet filter. Defense-in-depth: `macos.sh` already enables the macOS firewall in stealth mode, so a hostile-wifi attacker should see stealthed ports.

- `com.user.purplemux` — [purplemux](https://github.com/subicura/purplemux), web-native terminal multiplexer for Claude Code
  - Installed via `npm install -g purplemux` (services.sh handles this)
  - Listens on `*:8022` (no `--bind` flag upstream); access is intended through Tailscale Serve, not an app-level IP filter. Logs at `~/Library/Logs/purplemux.{out,err}.log`
  - Tailnet exposure: `tailscale serve --bg --https=443 --set-path=/ http://localhost:8022`
  - Restart: `launchctl kickstart -k gui/$(id -u)/com.user.purplemux`
- `com.user.code-server` — [code-server](https://github.com/coder/code-server), VS Code in the browser
  - Installed via Brewfile (`brew "code-server"`)
  - Reads `~/.config/code-server/config.yaml` (services.sh scaffolds with a random password and enforces `chmod 600`)
  - Binds to `127.0.0.1:8088`. Logs at `~/Library/Logs/code-server.{out,err}.log`
  - Tailnet exposure: `tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088`
  - Restart: `launchctl kickstart -k gui/$(id -u)/com.user.code-server`

**Shared agent config** — canonical `~/.agent/AGENTS.md` with shared rules, also symlinked to `~/.cursor/rules/AGENTS.md` before Claude Code setup. `~/.claude/CLAUDE.md` imports it via `@AGENTS.md`.

**Dotfiles symlinks** — zshrc, tmux.conf, gitconfig, gitignore_global, Claude Code settings, pretool-guard hook, skill-md-edit-warn hook, work-scope-guard hook. Codex config is copied as a mutable local file. `configs/mcp.json` is read by `scripts/claude.sh` for user-scope MCP registration.

**Web extraction** — use `defuddle parse <url> --markdown` for article-style extraction (local, LLM-friendly Markdown). For JS-heavy or auth-gated pages, use `agent-browser open <url> --profile "Default"` to reuse your logged-in Chrome session; if an agent-browser daemon is already running under another profile, close it first with `agent-browser close --all`.

**Agent safety and secrets** — Claude settings include `permissions.deny` for `.env*`, `secrets/`, `WebFetch`, and filesystem MCP access; MCP governance approves `chrome-devtools`, `serena`, and `codegraph` from the shared MCP config and denies filesystem servers by `serverName`. `pretool-guard` is a PreToolUse Bash hook that emits structured JSON `permissionDecision: "deny"` for destructive commands such as `git reset --hard`, force push, root `rm -rf`, curl/wget piped to shell, and direct dotenv reads. `skill-md-edit-warn` is a PostToolUse hook that reminds you to restart Claude after editing a skill file mid-session. Prefer ephemeral secret injection: `op run --env-file .env -- <command>` for 1Password or `sops exec-env secrets.enc.env '<command>'` for SOPS.

**Tailscale + Tailscale SSH** — private mesh VPN for remote access. Each device gets a stable `100.x.x.x` IP and `*.ts.net` hostname; no port forwarding, no public exposure. `tailscale.sh` runs `tailscale set --ssh` so inbound shell access can go through Tailscale (identity from the tailnet, ACL-gated in the admin console). Persistent sessions: `tailscale ssh user@<host> -- tmux attach`. OpenSSH (`systemsetup -setremotelogin on`, set in `macos.sh`) is enabled in parallel — Tailscale SSH is the primary path, OpenSSH stays as a fallback for tooling that doesn't speak the Tailscale layer. Free tier covers personal use.

**mosh** — UDP-based shell that survives network changes / roaming / disconnects. Bootstraps over SSH for auth (so OpenSSH must stay enabled) then switches to UDP ports 60000–61000. Useful on mobile hotspots or unstable links. Connect with `mosh user@host` or `mosh --ssh="tailscale ssh" user@host` to layer mosh on top of Tailscale SSH. The macOS Application Firewall is in stealth mode, so the first `mosh` session may need a manual exception for `mosh-server` (System Settings → Network → Firewall → Options).

**Tests** — bats-core suites under `tests/` cover `scripts/lib/common.sh` helpers, script syntax/conventions, config drift, GitHub Actions pinning, JSON/TOML validation, and `Brewfile` parsing. Run with `bats tests/`.

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
│   ├── codex.sh            # Codex CLI config + cmux skill + auth prompt
│   ├── skills.sh           # repo-local skills/plugin installer
│   ├── verify.sh           # repo smoke verifier
│   ├── lib/
│   │   └── common.sh       # shared helpers (info/warn/error/run_or_dry/link_file)
│   ├── hermes.sh           # Hermes Agent (Nous Research) installer wrapper
│   ├── services.sh         # purplemux + code-server LaunchAgent installer
│   ├── purplemux-launch.sh # LaunchAgent wrapper for purplemux (PATH + node resolution)
├── plugins/
│   └── local-skills/       # local Claude/Codex skill bundle
│   ├── code-server-launch.sh # LaunchAgent wrapper for code-server
│   └── tailscale.sh        # Tailscale VPN + `tailscale set --ssh`
├── configs/
│   ├── .zshrc
│   ├── .tmux.conf
│   ├── .gitconfig
│   ├── .gitconfig-personal
│   ├── .gitconfig-work
│   ├── .gitignore_global
│   ├── AGENTS.md           # canonical agent rules (Claude + Cursor)
│   ├── CLAUDE.md           # Claude Code wrapper (imports AGENTS.md)
│   ├── claude-settings.json
│   ├── mcp.json            # shared Claude MCP servers
│   ├── codex/
│   │   └── config.toml     # Codex CLI defaults + MCP servers
│   ├── com.user.purplemux.plist     # LaunchAgent template (sed-substituted at install)
│   ├── com.user.code-server.plist   # LaunchAgent template (sed-substituted at install)
│   ├── rtk-config.toml
│   └── hooks/
│       ├── pretool-guard.sh     # structured PreToolUse deny hook
│       ├── work-scope-guard.sh  # SessionStart advisory for work roots
│       └── skill-md-edit-warn.sh # PostToolUse reminder after editing skills
├── tests/                  # bats-core suites: run `bats tests/`
│   ├── common.bats
│   └── scripts.bats
└── company/                # (gitignored) optional company overlay — see company/README.md
```

## Company overlay (optional)

For environments that require company-internal configuration (private plugin
marketplaces, image registries, scoped npm registries, team-issued API keys),
`install.sh` automatically invokes `company/install.sh` if that path exists.

`company/` is a **git submodule** pointing at a separate, internally-hosted
repo (URL listed in `.gitmodules`). The submodule URL is visible publicly but
the repository itself is only accessible over the internal network with proper
auth — clone fails gracefully outside the company.

On a new machine:
```bash
git clone --recurse-submodules https://github.com/voidmatcha/dotfiles.git ~/dotfiles
# or, if already cloned:
git -C ~/dotfiles submodule update --init
```

See `company/README.md` for what lives in the overlay and how to maintain it.

## Run individual scripts

```bash
./scripts/brew.sh     # Homebrew only
./scripts/macos.sh    # macOS settings only
./scripts/dev.sh      # dev tools only
./scripts/shell.sh    # shell only
./scripts/git.sh      # Git only
./scripts/codex.sh    # Codex CLI only
```

## Dry run

Preview without making changes:

```bash
./install.sh --dry-run
```

## Separate Git accounts

Account selection is **remote-URL-based**, not directory-based — a repo's
location on disk doesn't matter, only its `remote.origin.url`:

- Remote matches the corporate git host → work account
  (`~/.gitconfig-work`)
- Anything else (or no remote yet) → personal account
  (`~/.gitconfig-personal`)

The exact host(s) that route to "work" live in `configs/.gitconfig`'s
`includeIf "hasconfig:remote.*.url:..."` blocks (currently set for the
maintainer's employer; fork and edit those patterns to match your own
internal git host — `https://`, `git@`, and `ssh://` URL forms are
each their own line). Requires **git 2.36+**.

The two account files (`configs/.gitconfig-personal` and `.gitconfig-work`)
carry only `user.name` and `user.email`. SSH `signingkey` paths are
**machine-specific** so they live in `~/.gitconfig.local` (gitignored),
with an optional `~/.gitconfig.local-work` for a separate work-account
signing key. `configs/.gitconfig` loads `~/.gitconfig.local` last, so it
always wins for signing/keys.

Run `git.sh` — it prompts for names and emails, then writes the two
account configs plus `~/.gitconfig.local` (default signing key path) and
`~/.gitconfig.local-work` (work signing key path).

### Where to put company repos: `~/work/`

Git identity routes by remote URL (above), but **MCP loading routes by
directory**. The company overlay writes its MCP config to
`~/work/.mcp.json` (project scope), and Claude Code picks it up only when
started inside `~/work/<repo>/`. So:

- **Keep company repos under `~/work/`** → company MCP servers
  (e.g. `github-enterprise`) auto-load on top of the personal set, and the
  overlay provides company MCP secrets such as `CONTEXT7_API_KEY` for
  `context7` rate limits.
- Any other location → company project MCPs are absent. On company overlay
  machines, clearly unapproved MCPs such as the `linkedin` scraper are pruned;
  provider-official MCPs such as Exa may remain user-scope only, but must not
  receive internal terms, URLs, source snippets, credentials, customer data, or
  personal information. Git author/signing still routes correctly via remote
  URL.

`git.sh` creates `~/work/` and `~/personal/` for you.

## SSH keys

`git.sh` generates separate keys for personal and work.
Add the public keys to GitHub after:

```bash
cat ~/.ssh/id_ed25519_personal.pub  # personal
cat ~/.ssh/id_ed25519_work.pub      # work
```
