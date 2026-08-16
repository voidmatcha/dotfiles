# dotfiles

macOS setup for AI coding assistants: [Claude Code] and [Codex].

One local operating layer for:

- shared assistant policy
- shared safety hooks and permission policy
- token-pressure measurement with explicit limits
- repeatable setup verification

Start points:

- **Policy**: [`configs/AGENTS.md`](configs/AGENTS.md), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/AGENTS.md`](configs/codex/AGENTS.md), [`configs/codex/config.toml`](configs/codex/config.toml)
- **Measurement**: [Evidence summary](#evidence-summary-2026-07-06), [`configs/RTK.md`](configs/RTK.md)
- **Safety**: [`configs/hooks/pretool-guard.sh`](configs/hooks/pretool-guard.sh), [`plugins/local-skills/skills`](plugins/local-skills/skills)
- **Verification**: [`scripts/verify.sh`](scripts/verify.sh), [`tests/scripts.bats`](tests/scripts.bats), [`scripts/doctor.sh`](scripts/doctor.sh)

## Evidence summary (~2026-07-06)

These are separate counters, not one additive savings total.

| Surface | Current evidence | Safe interpretation |
| --- | --- | --- |
| [RTK] ingress reduction | 23,903 global commands. 26.2M estimated tokens removed (57.3%). In this repo: 1.26M removed (63.5%). | Substantial command/tool-output reduction before transcript ingress. Not a bill-savings percentage. |
| Public usage ledger | [Tokscale]: 93.711B tokens and 95.8% cache-read through 2026-07-05. | Public token-mix snapshot. Not causality proof for one repo change. |

Cross-machine totals are omitted until each machine is refreshed with the same capture window.

## Install

Fresh macOS install:

```bash
curl -fsSL https://raw.githubusercontent.com/voidmatcha/dotfiles/main/bootstrap.sh | bash
```

Preview without changing the machine:

```bash
curl -fsSL https://raw.githubusercontent.com/voidmatcha/dotfiles/main/bootstrap.sh | bash -s -- --dry-run
```

Run from an existing clone:

```bash
cd ~/dotfiles
./install.sh
```

Update an existing machine:

```bash
./update.sh --check # preview: git pull + install.sh --dry-run --upgrade
./update.sh         # git pull --ff-only + install.sh --upgrade
./update.sh --no-pull
```

Health/status snapshot:

```bash
./scripts/doctor.sh
```

`bootstrap.sh` installs Xcode Command Line Tools when `git` is missing, clones this repo into `~/dotfiles`, and hands off to `./install.sh`. The `company/` overlay runs only when the submodule exists locally.

<details>
<summary>What gets installed</summary>

| Area | Installs/configures | Source |
| --- | --- | --- |
| macOS defaults | Dock, Finder, keyboard, screenshots, firewall, Touch ID sudo. | [`scripts/macos.sh`](scripts/macos.sh) |
| CLI packages | [Homebrew] tools, [Bats], [gitleaks], [uv], [gettext], [git-filter-repo], [Docker CLI]. | [`Brewfile`](Brewfile) |
| Language runtimes | [nvm], [Node.js] LTS, [Corepack], [pyenv], latest [Python] 3, [SDKMAN!], [OpenJDK] LTS, [Maven]. | [`scripts/dev.sh`](scripts/dev.sh) |
| Shell and Git | [Zsh] plugins, [direnv], personal/work Git identities, SSH signing via [OpenSSH]. | [`scripts/shell.sh`](scripts/shell.sh), [`scripts/git.sh`](scripts/git.sh) |
| Agent CLIs | [Claude Code], [Codex], [Hermes Agent]. | [`scripts/claude.sh`](scripts/claude.sh), [`scripts/codex.sh`](scripts/codex.sh), [`scripts/hermes.sh`](scripts/hermes.sh), [`scripts/dev.sh`](scripts/dev.sh) |
| Private remote access | [Tailscale], [Tailscale SSH], [OpenSSH], [code-server], [purplemux]. [Tailscale Serve] remains opt-in. | [`scripts/tailscale.sh`](scripts/tailscale.sh), [`scripts/services.sh`](scripts/services.sh) |

Run a focused installer when full setup is not needed:

```bash
./scripts/brew.sh
./scripts/macos.sh
./scripts/dev.sh
./scripts/shell.sh
./scripts/git.sh
./scripts/codex.sh
./scripts/claude.sh
./scripts/hermes.sh
./scripts/tailscale.sh
./scripts/services.sh
```

</details>

## Agent layer

The point is not to make [Claude Code] and [Codex] identical. The point is to keep policy, skills, MCP routing, and verification consistent while each tool keeps its native workflow.

Claude imports `@~/.agent/AGENTS.md` through [`configs/CLAUDE.md`](configs/CLAUDE.md). In plain terms, it imports ~/.agent/AGENTS.md.

Codex setup writes `~/.codex/config.toml` from [`configs/codex/config.toml`](configs/codex/config.toml). It enables `[features] goals = true`, keeps `mcp_servers` entries in generated TOML, and installs Codex skills with `scripts/skills.sh codex`.

| Surface | Role | Source |
| --- | --- | --- |
| [Claude Code] | Claude execution with shared AGENTS.md rules, hooks, MCP, and [RTK] policy. | [`scripts/claude.sh`](scripts/claude.sh), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/claude-settings.json`](configs/claude-settings.json) |
| [Codex] | Codex execution with goals, memories, and native subagents. | [`scripts/codex.sh`](scripts/codex.sh), [`configs/codex/config.toml`](configs/codex/config.toml) |
| [RTK] | Command-output compression before noisy shell output enters context. | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml) |
| Local skills | Repo-owned procedures for context pressure, handoff, verification, previews, cleanup, and provenance. | [`plugins/local-skills/skills`](plugins/local-skills/skills) |

`ResumerBar`/`agent-resumer` and `cmux-deck` are machine-local runtime
integrations, not components installed or configured by this repository. Do not
commit their generated shims, sockets, state, LaunchAgents, or injected shell
blocks here. The supported `cmux` references below mean the current cmux CLI and
display backend, not the separate `cmux-deck` project.

### Installed external skills and plugins

These are installed or enabled in addition to the repo local skills listed below. The `local-skills@dotfiles-local` plugin exposes those local skills to Claude.

| Use case | Item | What it does |
| --- | --- | --- |
| Pressure-test a plan. | [`grill-me`](scripts/skills.sh) | Standalone Claude and Codex skill installed from a pinned upstream ref. |
| Implement from Figma. | [`figma-implement-design`](scripts/skills.sh) | Codex skill installed from a pinned upstream ref. |
| See Claude session state. | [`claude-hud@claude-hud`](configs/claude-settings.json) | Shows a local Claude status HUD. |
| Audit skill inventory. | [`skills-janitor@skills-janitor`](configs/claude-settings.json) | Helps inspect and clean up installed skills. |
| Wrap Claude sessions. | [`session-wrap`](scripts/skills.sh) | Claude session wrapping plugin pinned by the installer. |
| Use Claude workflow helpers. | [`superpowers`](configs/claude-settings.json) | Enables official workflow helpers while noisy subskills stay disabled. |
| Review frontend design. | [`frontend-design`](configs/claude-settings.json) | Adds official frontend design guidance. |
| Manage CLAUDE.md files. | [`claude-md-management`](configs/claude-settings.json) | Adds official guidance for CLAUDE.md style files. |
| Work with hooks. | [`hookify`](configs/claude-settings.json) | Adds official hook workflow helpers. |
| Review security basics. | [`security-guidance`](configs/claude-settings.json) | Adds official security guidance. |
| Review code broadly. | [`comprehensive-review`](configs/claude-settings.json) | Adds a Claude code review workflow bundle. |
| Generate docs. | [`documentation-generation`](configs/claude-settings.json) | Adds a Claude documentation workflow bundle. |
| Keep Claude memory. | [`claude-mem`](configs/claude-settings.json) | Enables the Claude memory plugin through local settings. |
| Review with Codex handoff. | [`review-loop@hamel-review`](configs/claude-settings.json) | Listed in settings for review-loop workflows and disabled by default. |
| Work with Obsidian notes. | [`obsidian-skills`](scripts/claude.sh) | Claude plugin installed from `kepano/obsidian-skills`. |

## Local skills: why they exist

Local skills turn recurring session decisions into named, checkable procedures. They are listed one-by-one so each can be audited later.

| Use case | Item | What it does |
| --- | --- | --- |
| Need public internet evidence beyond the repo. | [`agent-reach`](plugins/local-skills/skills/agent-reach/SKILL.md) | Routes public web, GitHub, social, video, and RSS research while keeping internal URLs out of hosted readers. |
| Clean stuck or runaway agent processes. | [`agent-reap`](plugins/local-skills/skills/agent-reap/SKILL.md) | Finds orphaned Claude or Codex related processes. Killing remains explicit. |
| Decide what agent surfaces to prune. | [`agent-usage-audit`](plugins/local-skills/skills/agent-usage-audit/SKILL.md) | Audits installed agents, skills, commands, MCPs, and recent usage. |
| Diagnose stale code intelligence. | [`code-intel-doctor`](plugins/local-skills/skills/code-intel-doctor/SKILL.md) | Checks codegraph and serena setup, Codex config, per-repo indexes, and live CodeGraph status; `--strict` fails closed on unknown status fields. |
| Decide continue, compact, clear, or hand off. | [`context-check`](plugins/local-skills/skills/context-check/SKILL.md) | Reads context, cache, and handoff pressure before changing session state. |
| Apply dotfiles changes to this machine. | [`dotfiles-sync`](plugins/local-skills/skills/dotfiles-sync/SKILL.md) | Judges the LLM tooling layer — plugin delivery, hook registration, skill pins, and which side wins when repo and machine diverge — then delegates every mutation to `update.sh`. |
| Verify dotfiles before install or publish. | [`dotfiles-verify`](plugins/local-skills/skills/dotfiles-verify/SKILL.md) | Runs install, config, and plugin smoke checks for this repo. |
| Transfer work to another session. | [`handover`](plugins/local-skills/skills/handover/SKILL.md) | Creates durable handoff artifacts and fail-closed ACK or READY checks. |
| Debug a bug, regression, or flaky failure. | [`hypothesis-debugging`](plugins/local-skills/skills/hypothesis-debugging/SKILL.md) | Separates facts from assumptions and tracks falsifiable hypotheses. |
| Mine local agent sessions for repeated feedback. | [`session-feedback-audit`](plugins/local-skills/skills/session-feedback-audit/SKILL.md) | Extracts recurring corrections and re-requests from local JSONL with extensible phrase pattern packs, then produces rules only from cross-file evidence. |
| Review terminology in Korean technical writing. | [`korean-technical-terminology`](plugins/local-skills/skills/korean-technical-terminology/SKILL.md) | Keeps canonical English where precision matters, follows established Korean usage, and rewrites awkward calques without becoming a general grammar checker. |
| Rewrite AI-sounding Korean prose so it reads as human-written. | [`humanize-korean`](plugins/local-skills/skills/humanize-korean/SKILL.md) | Detects 40+ tells across ten categories — translationese, mechanical parallelism, passive overuse, uniform rhythm — and rewrites style only, leaving the content untouched. Technical-document editing goes to `korean-tech-humanizer` instead. |
| Curate the llmwiki vault by hand. | [`llmwiki-curate`](plugins/local-skills/skills/llmwiki-curate/SKILL.md) | Writes the two things the nightly job cannot: `## 실패한 시도` lessons judged one candidate at a time, and Library notes from material dropped in `raw/`. Collection, compile, and snapshot stay automatic and LLM-free. |
| Track job postings in the llmwiki vault. | [`job-watch`](plugins/local-skills/skills/job-watch/SKILL.md) | Refreshes tracked postings, confirms whether one is still open, registers new ones, and scans target companies. Status refresh is deterministic and script-driven; judgement stays with the reader. |
| Serve a local report or build preview. | [`local-preview-server`](plugins/local-skills/skills/local-preview-server/SKILL.md) | Starts verified localhost or tailnet preview URLs. Default bind is `127.0.0.1`. |
| Stress-test a risky plan. | [`premortem`](plugins/local-skills/skills/premortem/SKILL.md) | Lists likely failure modes before execution. |
| Track imported workflow assets. | [`source-provenance`](plugins/local-skills/skills/source-provenance/SKILL.md) | Records standard Agent Skills provenance metadata and audits source, license, import mode, and local modifications. |
| Fact-check README, PR, or report claims. | [`verify-output`](plugins/local-skills/skills/verify-output/SKILL.md) | Extracts claims, tries to refute them, and classifies the result. |
| Avoid wrong-surface data routing. | [`work-scope-guard`](plugins/local-skills/skills/work-scope-guard/SKILL.md) | Shows work and company scope reminders before sensitive data enters the wrong tool. |
| Open worktrees in browser VS Code. | [`worktree-open`](plugins/local-skills/skills/worktree-open/SKILL.md) | Builds deterministic code-server links for one worktree or all worktrees. |

`handover` owns context/session transfer. For a visible backend, use [`display-adapter-contract.md`](plugins/local-skills/skills/handover/references/display-adapter-contract.md) and [`purplemux-display.md`](plugins/local-skills/skills/handover/references/purplemux-display.md). `cmux` and `purplemux` stay display/control backends.

`asset-improver` is retained under [`plugins/local-skills/quarantine/`](plugins/local-skills/quarantine/) for possible salvage, but it is not published as a skill. Its old workflow depends on skill names that are not portable across the installed runtimes, contains a machine-specific eval path, and can perform destructive Git recovery.

Keep `agent-reach` health checks non-mutating: use `agent-reach --version`, not
`agent-reach doctor`. The upstream doctor can recreate generic copies under
shared skill roots and shadow this repo's public-only adaptation. If upstream
setup is intentionally rerun, reinstall both local targets with
`scripts/skills.sh claude` and `scripts/skills.sh codex`, then restart active
Claude/Codex sessions.

## MCP governance and Tool routing

| Surface | Config | Policy |
| --- | --- | --- |
| [Claude Code] MCP | [`configs/mcp.json`](configs/mcp.json) | Registers local and hosted MCPs for Claude Code. Hooks and deny rules catch common mistakes. |
| [Codex] MCP | [`configs/codex/config.toml`](configs/codex/config.toml) | Registers [Chrome DevTools MCP][chrome-devtools-mcp], [serena], [codegraph], [context7], [OpenAI Docs MCP], and personal/default [Figma hosted MCP][Figma MCP]. |
| Company/local fallback | `company/` overlay when present | Uses company-scoped MCP or local browser surfaces when hosted tools are inappropriate. |

Do not route internal URLs through hosted tools such as [Exa], [Jina Reader], or personal/default [Figma hosted MCP][Figma MCP]. Company Figma context is separate. Use the company fallback (`figma-developer-mcp`) or a local browser surface.

[agent-browser] is a qualitative token-pressure control for targeted browser observation and authenticated browsing. It is not a numeric savings claim.

### Tool routing

| Task | Default tool | Reason |
| --- | --- | --- |
| Explain code flow, route handlers, or symbol traces. | [codegraph] | Pre-indexed graph for cross-file flow. |
| Rename, edit, or inspect references. | [serena] | LSP-backed symbol-aware edits and references. |
| Clean public web page extraction. | [Jina Reader] or [defuddle] | Fast Markdown extraction for public pages. Example: `defuddle parse <url> --markdown`. |
| Broad public web research. | [Exa] | Public search only, not for sensitive or internal URLs. |
| Authenticated or sensitive browsing. | [agent-browser] or local browser | Keeps auth and internal context out of hosted readers. |
| Throwaway browser automation. | [Chrome DevTools MCP][chrome-devtools-mcp] | Clean browser automation for local targets. |
| Knowledge graph exploration. | [graphify] | Installed as a Claude/Codex skill with `graphify install --platform claude` and `graphify install --platform codex`. |
| Session context policy. | [`context-check`](plugins/local-skills/skills/context-check/SKILL.md) | Returns continue, compact, clear, or handoff advice. |

Web tooling note: [defuddle] is installed with `npm install -g defuddle`. [graphify] is installed by [`scripts/dev.sh`](scripts/dev.sh).

#### Research fact policy

`configs/AGENTS.md` requires external facts to be verified where the research
happens, not where it is reported. The reason is failure-mode specific: a false
claim relayed at report time has already shaped the reasoning that cites it, and
re-checking a finished report is both late and expensive. At research time the
subagent still has its sources open.

Rules a research subagent follows:

- **Facts vs interpretation.** Acquisitions, shutdowns, funding, licence
  changes, product retirements, and version/date claims are facts. "Threat is
  low", "worth borrowing" are interpretation. Report them in separate sections.
- **Evidence bar for facts.** A primary source (company announcement, the
  project's own repo/registry, or a command whose output is quoted) or two
  independent major outlets. A personal blog, SEO roundup, vendor marketing
  page, or aggregator alone is never sufficient — label it unverified or drop it.
- **Refute first.** [`verify-output`](plugins/local-skills/skills/verify-output/SKILL.md)
  searches for disconfirming evidence before accepting a claim. Run it on the
  fact list, not on the prose.
- **Verify hardest what you want to be true.** A claim that supports the
  conclusion already forming gets *more* scrutiny, not less. This is the failure
  that motivated the rule.
- **Subagent output is a draft, not a source.** Never quote an unchecked fact
  claim onward; check the cited link's nature before repeating its content.

## Claude Code operational tripwires, not security controls

Some local sessions intentionally run with broad filesystem permissions. These Claude Code tripwires are not a security boundary. They do not protect a separate [Codex] `danger-full-access` session. They catch common mistakes. Sandboxing, review, and secret management still do the security work.

| Guard | Surface | Catches |
| --- | --- | --- |
| [`pretool-guard`](configs/hooks/pretool-guard.sh) | Claude `PreToolUse` hook for Bash. | Broad destructive Bash patterns before the tool call runs. |
| [`skill-md-edit-warn`](configs/hooks/skill-md-edit-warn.sh) | Claude `PostToolUse` warning. | `SKILL.md` edits made after the session already loaded skill instructions. |
| `permissions.deny` | [`configs/claude-settings.json`](configs/claude-settings.json) | Known secret paths and risky hosted-tool surfaces in Claude Code. |
| [`work-scope-guard`](plugins/local-skills/skills/work-scope-guard/SKILL.md) | Local skill. | Company/work-scope routing reminders. |

## Safety and local previews

Prefer localhost and private tailnet paths. Local previews bind localhost by default. Access from another machine goes through [Tailscale Serve] and tailnet ACLs.

| Need | Default path | Exposure |
| --- | --- | --- |
| Open a browser IDE for a worktree. | [`worktree-open`](plugins/local-skills/skills/worktree-open/SKILL.md) | Local [code-server] URL, or a [Tailscale] URL when tailnet access is available. |
| Serve a report or static build. | [`local-preview-server`](plugins/local-skills/skills/local-preview-server/SKILL.md) | The default bind address is `127.0.0.1`. |
| Share a preview inside the tailnet. | `--tailscale-serve` | Uses [Tailscale Serve] and tailnet ACLs. |
| Gate optional LaunchAgents. | [`scripts/services.sh`](scripts/services.sh) | It skips loading LaunchAgents when dependencies are missing so partial installs stay usable. |

```bash
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh start --path ./report.html --port 8377
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh start --path ./dist --tailscale-serve
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh status --port 8377
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh stop --port 8377
```

## Verification

Run the full verifier before claiming installer behavior:

```bash
bash scripts/verify.sh --full
```

Useful focused checks:

```bash
bats tests/
bash scripts/verify.sh --quick
bash scripts/secret-scan.sh --required
bash scripts/doctor.sh
python3 scripts/code_intel_doctor.py --json --strict .
python3 scripts/source_provenance_audit.py --strict --format json
```

When local skill content changes, keep the marketplace, Claude plugin, and
Codex plugin manifest versions aligned before reinstalling. Installation is not
complete until the published `plugins/local-skills/skills/` tree matches the
Claude plugin cache and every corresponding `~/.codex/skills/<name>` directory.
Quarantined assets must remain outside the published `skills/` root.

Pre-push protection is managed by [lefthook]. `install.sh` runs `lefthook install` when available, and `lefthook.yml` runs both `scripts/verify.sh` and required [gitleaks] scans of the worktree plus all commits reachable from local refs (`--all`), including non-checked-out branches and tags. Install missing hook tooling with `./scripts/brew.sh`.

Tests cover shell and Python syntax, ShellCheck, Python unit tests, JSON/TOML/plist parsing, skill/plugin manifests, hook behavior, [Codex] TOML validation, `Brewfile` parsing, outgoing-history secret scans, doctor/status checks, and local skill helpers. `--full` fails closed when ShellCheck or [Bats] is unavailable; use `--quick` only when the complete lint/Bats gate is intentionally out of scope.

## Layout

```text
dotfiles/
├── install.sh
├── Brewfile
├── README.md
├── scripts/
├── configs/
├── plugins/local-skills/
├── tests/
└── company/
```

## Company overlay

For environments with internal package registries, private plugin marketplaces, or scoped MCP configuration, `install.sh` invokes `company/install.sh` when the `company/` submodule exists. Keep company repos under `~/work/` so project-scoped MCP work-scope guidance applies.

```bash
git clone --recurse-submodules https://github.com/voidmatcha/dotfiles.git ~/dotfiles
```

If you cloned first, initialize the overlay later:

```bash
git -C ~/dotfiles submodule update --init
```

See [`company/README.md`](company/README.md) for overlay maintenance.

[agent-browser]: https://github.com/vercel-labs/agent-browser
[Bats]: https://github.com/bats-core/bats-core
[chrome-devtools-mcp]: https://github.com/ChromeDevTools/chrome-devtools-mcp
[Claude Code]: https://docs.anthropic.com/en/docs/claude-code/overview
[code-server]: https://coder.com/docs/code-server/latest
[codegraph]: https://www.npmjs.com/package/@colbymchenry/codegraph
[Codex]: https://github.com/openai/codex
[context7]: https://github.com/upstash/context7
[Corepack]: https://nodejs.org/api/corepack.html
[defuddle]: https://github.com/kepano/defuddle
[direnv]: https://direnv.net/
[Docker CLI]: https://docs.docker.com/reference/cli/docker/
[Exa]: https://exa.ai/
[Figma MCP]: https://help.figma.com/hc/en-us/articles/32132100833559-Guide-to-the-Dev-Mode-MCP-Server
[gettext]: https://www.gnu.org/software/gettext/
[git-filter-repo]: https://github.com/newren/git-filter-repo
[gitleaks]: https://github.com/gitleaks/gitleaks
[graphify]: https://github.com/safishamsi/graphify
[Hermes Agent]: https://github.com/NousResearch/hermes-agent
[Homebrew]: https://brew.sh/
[Jina Reader]: https://jina.ai/reader/
[lefthook]: https://lefthook.dev/
[Maven]: https://maven.apache.org/
[nvm]: https://github.com/nvm-sh/nvm
[Node.js]: https://nodejs.org/
[OpenAI Docs MCP]: https://developers.openai.com/mcp
[OpenJDK]: https://openjdk.org/
[OpenSSH]: https://www.openssh.com/
[purplemux]: https://github.com/subicura/purplemux
[pyenv]: https://github.com/pyenv/pyenv
[Python]: https://www.python.org/
[RTK]: https://www.rtk-ai.app/
[SDKMAN!]: https://sdkman.io/
[serena]: https://github.com/oraios/serena
[Tailscale]: https://tailscale.com/
[Tailscale Serve]: https://tailscale.com/kb/1242/tailscale-serve/
[Tailscale SSH]: https://tailscale.com/kb/1193/tailscale-ssh/
[Tokscale]: https://tokscale.ai/u/voidmatcha
[uv]: https://docs.astral.sh/uv/
[Zsh]: https://www.zsh.org/
