# dotfiles

A reproducible macOS setup for AI-assisted development.

This is not a config dump. The repo is an operating system for agentic development:
it installs the local environment, keeps Claude Code and Codex on one shared contract,
routes MCP/browser tools deliberately, measures token behavior, and tests the workflow
code that makes those habits repeatable.

The core thesis is evidence-bound: optimize what enters context, keep cacheable prefixes
stable, and hand off long sessions before carrying context costs more than reuse is worth.

## What to review first

| Reviewer question | Start with | What it proves |
| --- | --- | --- |
| Are Claude Code, Codex, and OMX governed by one contract? | [`configs/AGENTS.md`](configs/AGENTS.md), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/config.toml`](configs/codex/config.toml) | One policy layer exists, while each tool keeps its native workflow. |
| Are token-efficiency claims measured? | [Tokscale], `rtk gain --history`, [`configs/RTK.md`](configs/RTK.md) | Public token-mix snapshot plus local command-output compression histories. |
| Are hosted and local tools separated? | [`configs/mcp.json`](configs/mcp.json), [`configs/codex/config.toml`](configs/codex/config.toml), [`configs/hooks/pretool-guard.sh`](configs/hooks/pretool-guard.sh) | Hosted readers, browser surfaces, and local MCPs are routed explicitly. |
| Can setup changes be verified? | [`scripts/verify.sh`](scripts/verify.sh), [`tests/scripts.bats`](tests/scripts.bats) | Installer, hook, config, plugin, and skill behavior is testable. |
| Can local work be previewed without broad exposure? | [`scripts/services.sh`](scripts/services.sh), [`plugins/local-skills/skills/local-preview-server/SKILL.md`](plugins/local-skills/skills/local-preview-server/SKILL.md) | Previews default to localhost and use [Tailscale Serve] only when remote access is intentional. |

## Design at a glance

| Design choice | What it does | Evidence |
| --- | --- | --- |
| Shared agent contract | Routes [Claude Code], [Codex], and [OMX] through one AGENTS.md contract. | [`configs/AGENTS.md`](configs/AGENTS.md), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/config.toml`](configs/codex/config.toml) |
| Explicit tool surfaces | Documents MCP servers, hosted readers, browser surfaces, and destructive-command tripwires. | [`configs/mcp.json`](configs/mcp.json), [`configs/codex/config.toml`](configs/codex/config.toml), [`configs/hooks/pretool-guard.sh`](configs/hooks/pretool-guard.sh) |
| Tool-output compression | Uses [RTK] before noisy shell output becomes transcript context. | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml), `rtk gain --history` |
| Session lifecycle checks | Makes continue, compact, clear, handoff, preview, and verify decisions repeatable. | [`plugins/local-skills/skills`](plugins/local-skills/skills) |
| Private remote access | Keeps browser IDEs and previews local-first, with explicit tailnet exposure. | [`scripts/tailscale.sh`](scripts/tailscale.sh), [`scripts/services.sh`](scripts/services.sh) |
| Verification culture | Treats dotfiles automation as production code. | [`scripts/verify.sh`](scripts/verify.sh), [`tests/`](tests/) |

## Evidence ledger

Quantitative claims use two scoped sources:

1. [Tokscale], a public token-mix snapshot.
2. `rtk gain --history`, local command-output compression histories.

[Tokscale] is a shareable dashboard snapshot, not causality proof by itself. [RTK]
measures tool output removed before transcript ingress, not total cost saved.

[Tokscale] source captured on 2026-06-17.

| [Tokscale] category | Share | Tokens |
| --- | ---: | ---: |
| Input | 1.0% | 727.5M |
| Output | 0.4% | 276.2M |
| Cache Read | 96.2% | 69.4B |
| Cache Write | 2.4% | 1.7B |
| Reasoning | 0.02% | 16.8M |

[Tokscale] window: 72.108946182B total tokens, $50,017.9449 total cost,
9,344 sessions, 185 active days, date range 2025-09-21 to 2026-06-17.

| [RTK] export | Commands | Raw output | Delivered output | Saved | Compression |
| --- | ---: | ---: | ---: | ---: | ---: |
| Machine A [RTK] history | 26,092 | 101.4M | 27.9M | 73.6M | 72.6% |
| Machine B [RTK] history | 103,434 | 96.1M | 40.9M | 55.4M | 57.6% |
| Combined cross-machine snapshot | 129,526 | 197.5M | 68.8M | about 129.0M | about 65.3% |

Combined [RTK] compression is weighted by raw output:
`(73.6M + 55.4M) / (101.4M + 96.1M)`, not the average of `72.6%` and `57.6%`.

Safe claims:

- `about 40.8x reuse`, from [Tokscale] Cache Read divided by Cache Write.
- `about 3.4% new-content share`, from [Tokscale] Input plus Cache Write divided by total tokens.
- `about 65.3% RTK tool-output compression across two machine histories`.
- `Cache Read about 96.2%`, as a [Tokscale] category share.

Do not claim:

- `65.3% cost reduction`.
- `96.2% efficiency`.
- exact total-spend contribution from [RTK] without a matched control run.
- `optimal`, `minimized`, or best-possible cost.

Open measurement items:

- Treat the combined [RTK] row as a cross-machine snapshot, not a deduplicated central database total.
- Track [RTK] bypass and rerun rate before claiming compression never causes hidden rework.
- Align [Tokscale], [RTK], and local usage-export windows before computing total-spend attribution.

## External research applied

Recent research and repo review reinforced the same design direction already present here:
agent efficiency is a context assembly problem, not just prompt-shortening.

| External pattern | What it says | Applied here |
| --- | --- | --- |
| [OpenAI prompt caching] | Cached-token accounting depends on stable repeated prefixes; static content should come first and variable content last. | Keep AGENTS/CLAUDE/Codex contracts compact and stable; avoid dynamic tool churn in the prefix. |
| [Claude Code monitoring] | Claude Code can export usage, cost, tool activity, and cache-read/cache-creation fields through OpenTelemetry. | Keep `context-check` advisory and add OTel/local export to the measurement roadmap instead of inventing cost claims. |
| [Braintrust token tracking] | Useful token tracking separates call-level usage, context-window pressure, and per-step agent traces. | The README separates [Tokscale] mix, [RTK] tool-output compression, and future step-level evidence. |
| [ccusage], [tokenwatch], [tokenusage], [TokenTracker] | Strong usage tools are local-first and exportable; they avoid uploading prompts or paths. | `scripts/dev.sh` installs `ccusage`; the roadmap asks for sanitized local exports beside public snapshots. |

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

`bootstrap.sh` installs Xcode Command Line Tools when `git` is missing, clones this
repo into `~/dotfiles`, and hands off to `./install.sh`. The `company/` overlay runs
only when the submodule exists locally.

<details>
<summary>What gets installed</summary>

| Area | Installs/configures | Source |
| --- | --- | --- |
| macOS defaults | Dock, Finder, keyboard, screenshots, firewall, Touch ID sudo. | [`scripts/macos.sh`](scripts/macos.sh) |
| CLI packages | [Homebrew] tools, [Bats], [uv], [gettext], [git-filter-repo], [Docker CLI]. | [`Brewfile`](Brewfile) |
| Language runtimes | [nvm], [Node.js] LTS, [Corepack], [pyenv], latest [Python] 3, [SDKMAN!], [OpenJDK] LTS, [Maven]. | [`scripts/dev.sh`](scripts/dev.sh) |
| Shell and Git | [Zsh] plugins, [direnv], personal/work Git identities, SSH signing via [OpenSSH]. | [`scripts/shell.sh`](scripts/shell.sh), [`scripts/git.sh`](scripts/git.sh) |
| Agent CLIs | [Claude Code], [Codex], [Hermes Agent], [OMX], [agent-resumer]. | [`scripts/claude.sh`](scripts/claude.sh), [`scripts/codex.sh`](scripts/codex.sh), [`scripts/hermes.sh`](scripts/hermes.sh), [`scripts/dev.sh`](scripts/dev.sh) |
| Remote access | [Tailscale], [Tailscale SSH], [OpenSSH], [code-server], [purplemux]. | [`scripts/tailscale.sh`](scripts/tailscale.sh), [`scripts/services.sh`](scripts/services.sh) |

Run one focused installer when you do not want the full setup:

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

The point is not to make [Claude Code] and [Codex] identical. The point is to keep
policy, skills, MCP routing, and verification consistent while each tool keeps its native
workflow.

| Surface | Role | Source |
| --- | --- | --- |
| [Claude Code] | Claude execution with shared AGENTS.md rules, hooks, MCP, and [RTK] policy. | [`scripts/claude.sh`](scripts/claude.sh), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/claude-settings.json`](configs/claude-settings.json) |
| [Codex (with OMX)][Codex] | Codex execution with [OMX] workflows, goals, memories, and native subagents. | [`scripts/codex.sh`](scripts/codex.sh), [`configs/codex/config.toml`](configs/codex/config.toml) |
| [Headroom] | Optional `claudeh`, `codexh`, and `omxh` wrappers for reversible compression and cache-aware routing. | [`scripts/headroom-agent.sh`](scripts/headroom-agent.sh), [`scripts/headroom.sh`](scripts/headroom.sh) |
| [agent-resumer] | Pane-aware auto-resume supervisor for Claude/Codex/OMX/OpenCode usage-limit resets. | [`scripts/dev.sh`](scripts/dev.sh), [`scripts/agent-resumer-launch.sh`](scripts/agent-resumer-launch.sh) |
| [RTK] | Command-output compression policy before noisy shell output enters context. | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml) |
| Local skills | Repo-owned procedures for context pressure, handoff, verification, previews, cleanup, and provenance. | [`plugins/local-skills/skills`](plugins/local-skills/skills) |

<details>
<summary>Claude Code setup</summary>

| Layer | Source | Purpose |
| --- | --- | --- |
| Shared prompt | [`configs/CLAUDE.md`](configs/CLAUDE.md) | Imports `@~/.agent/AGENTS.md`; in plain terms, it imports ~/.agent/AGENTS.md and [RTK] notes instead of duplicating long instructions. |
| Runtime settings | [`configs/claude-settings.json`](configs/claude-settings.json) | Defines hooks, deny rules, statusline, and plugin configuration. |
| MCP catalog | [`configs/mcp.json`](configs/mcp.json) | Registers local and hosted MCP servers for Claude Code. |
| Local skills plugin | [`plugins/local-skills`](plugins/local-skills) | Ships repo-specific skills into Claude/Codex surfaces. |

Installed [Claude Code] plugins include [`claude-hud@claude-hud`][claude-hud],
[`skills-janitor@skills-janitor`][skills-janitor], [`review-loop@hamel-review`][review-loop],
[`local-skills@dotfiles-local`](plugins/local-skills), [`session-wrap`][session-wrap], and
[`obsidian-skills`][obsidian-skills].

</details>

<details>
<summary>Codex and OMX setup</summary>

| Layer | Source | Purpose |
| --- | --- | --- |
| Prompt contract | [`configs/codex/config.toml`](configs/codex/config.toml) | Installed to `~/.codex/config.toml`; sets `developer_instructions` to the [Codex]/[OMX] AGENTS.md contract. |
| Goals and memories | [`configs/codex/config.toml`](configs/codex/config.toml) | Keeps `[features] goals = true` and enables built-in [Codex Memories]. |
| Native subagents | `.codex/agents` after install | Keeps role prompts separate from procedural skills. |
| Skills | `.codex/skills` after install | `scripts/skills.sh codex` installs local skills from [`plugins/local-skills`](plugins/local-skills). |
| MCP | [`configs/codex/config.toml`](configs/codex/config.toml) | The `mcp_servers` table registers [Chrome DevTools MCP][chrome-devtools-mcp], [serena], [codegraph], [context7], [OpenAI Docs MCP], and the personal/default [Figma hosted MCP][Figma MCP]. |

Company Figma context is separate from the personal/default hosted Figma path. The company
fallback uses `figma-developer-mcp` or a local browser surface and disables hosted Codex Figma
when that boundary matters.

</details>

## Local skills: why they exist

Local skills turn recurring session decisions into named, repeatable procedures. They are not
"more prompts" for their own sake; each one exists because a repeated failure mode, handoff
step, or evidence-gathering path was worth making deterministic.

| Situation | Use | Why |
| --- | --- | --- |
| Continue, compact, clear, or hand off? | [`context-check`](plugins/local-skills/skills/context-check/SKILL.md) | Reads idle, prompt, transcript, and headroom pressure before changing session state. |
| Move work to a fresh Claude/Codex/OMX session, cross-check agents, or run a bounded handoff in a visible backend? | [`handover`](plugins/local-skills/skills/handover/SKILL.md) | Creates transferable task artifacts and receiver-side readiness checks; cross-agent work uses [`cross-agent-coordination.md`](plugins/local-skills/skills/handover/references/cross-agent-coordination.md), while visible continuation uses [`display-adapter-contract.md`](plugins/local-skills/skills/handover/references/display-adapter-contract.md), [`cmux-display.md`](plugins/local-skills/skills/handover/references/cmux-display.md), or [`purplemux-display.md`](plugins/local-skills/skills/handover/references/purplemux-display.md). |
| Serve a report, build artifact, or local directory privately? | [`local-preview-server`](plugins/local-skills/skills/local-preview-server/SKILL.md) | Uses localhost/Tailscale-style preview paths instead of broad `0.0.0.0` exposure by default. |
| Open the current worktree in browser VS Code? | [`worktree-open`](plugins/local-skills/skills/worktree-open/SKILL.md) | Builds deterministic code-server folder/workspace URLs for one worktree or all worktrees. |
| Verify the dotfiles repo before install or publish? | [`dotfiles-verify`](plugins/local-skills/skills/dotfiles-verify/SKILL.md) | Runs the repo's install/config/plugin smoke checks. |
| Clean up stuck agent processes? | [`agent-reap`](plugins/local-skills/skills/agent-reap/SKILL.md) | Conservative process scan; killing remains an explicit action. |
| Prune agents, commands, skills, MCPs, or token-pressure sources? | [`agent-usage-audit`](plugins/local-skills/skills/agent-usage-audit/SKILL.md) | Usage-grounded pruning plus `session-report` source summaries. |
| Need public internet evidence beyond the local repo? | [`agent-reach`](plugins/local-skills/skills/agent-reach/SKILL.md) | Routes public web/GitHub/social/video/RSS lookup while keeping internal URLs out of hosted readers. |
| Diagnose stale code intelligence? | [`code-intel-doctor`](plugins/local-skills/skills/code-intel-doctor/SKILL.md) | MCP config, installed-tool, and index-health checks. |
| Avoid sending work data through the wrong surface? | [`work-scope-guard`](plugins/local-skills/skills/work-scope-guard/SKILL.md) | Fail-open reminders for company/work scopes. |
| Track imported workflow assets? | [`source-provenance`](plugins/local-skills/skills/source-provenance/SKILL.md) | Source, license, and local-modification records. |

`handover` owns context/session transfer and long-running agent coordination. `cmux` and
`purplemux` stay display/control backends for workspaces, tabs, surfaces, focus, and terminal health.

## Token-efficiency design

This repo targets token cost at five points: what enters context, whether cache prefixes stay
stable, how idle sessions decay, when a session should hand off, and whether the optimization
layer remains measured.

| Cost surface | Repo mechanism | Evidence |
| --- | --- | --- |
| Context ingress | [RTK] compresses noisy command output before transcript ingress. | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml), `rtk gain --history` |
| Cache prefix stability | [Claude Code] keeps a compact `CLAUDE.md`; [Codex] keeps one `developer_instructions` contract and explicit MCP entries. | [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/config.toml`](configs/codex/config.toml) |
| Idle and context pressure | `context-check` reads idle, prompt, transcript, and [Headroom] pressure before recommending continue, compact, clear, or handoff. | [`plugins/local-skills/skills/context-check/SKILL.md`](plugins/local-skills/skills/context-check/SKILL.md) |
| Long-session handoff | `handover` carries distilled state into fresh [Claude Code], [Codex], or [OMX] sessions. | [`plugins/local-skills/skills/handover/SKILL.md`](plugins/local-skills/skills/handover/SKILL.md) |
| Survival under real work | Hooks fail open, bypasses exist, and the verifier covers hooks plus skill helpers. | [`configs/hooks`](configs/hooks), [`scripts/verify.sh`](scripts/verify.sh), [`tests/`](tests/) |

Only [RTK] and [Tokscale] get numeric published claims here. `rtk_safety_report.py` and
`agent_usage_audit.py session-report` create local evidence for future claims. [agent-browser] is a
qualitative token-pressure control for targeted browser observation and authenticated browsing, not a numeric savings claim. [Headroom], `context-check`, `handover`,
[Jina Reader], [defuddle], [codegraph], and [serena] are structural controls.
They reduce token pressure by shaping what gets loaded or carried, but this README does not
assign them a savings percentage.

<details>
<summary>Five principles behind the setup</summary>

1. **Stateless billing rewards ingress control.** A token that never enters the transcript is
   not reread on later calls. [RTK] attacks noisy tool output at ingress; scout-style batching
   attacks repeated call overhead.
2. **Cache is prefix-sensitive.** [OpenAI prompt caching] documents that static content should
   precede variable content and cached-token fields must be tracked. This repo keeps shared
   prompt contracts compact and avoids pretending every tool list should be loaded everywhere.
3. **Cache has a clock.** The point of `context-check` is to make idle/context pressure visible
   before a session drifts into an expensive or brittle state.
4. **Long sessions are not free.** A high cache-read share helps only while reuse beats the cost
   of carrying stale context. `handover` exists so clearing context can be deliberate, not lossy.
5. **Unmeasured optimization is a guess.** [RTK] gain, [Tokscale] summaries, local usage tools,
   [Bats], and `scripts/verify.sh` keep the efficiency layer tied to evidence.

</details>

## Measurement roadmap

These are not current achievements. They are the next artifacts needed to make the efficiency
story harder to attack.

| Gap | Next artifact | Why it matters | Source pattern |
| --- | --- | --- | --- |
| Public snapshot depends on [Tokscale]. | Sanitized local `ccusage` or `@ccusage/codex` JSON/Markdown export. | Makes token mix reproducible from local logs without uploading prompts or paths. | [ccusage], [tokenwatch], [tokenusage], [TokenTracker] |
| [RTK] safety needs local history. | `scripts/rtk_safety_report.py` over `RTK_HOOK_AUDIT=1` logs and privacy-preserving JSONL events. | Counts fallback, explicit bypass, and repeat-after-compression candidates without raw outputs. | [RTK] `hook-audit` plus local reporter. |
| Tool-output compression and token dashboard windows differ. | Shared date-window export for [Tokscale], [RTK], and local usage logs. | Avoids mixing periods before any spend-attribution claim. | [Braintrust token tracking] attribution discipline. |
| Cache semantics depend on provider/client. | Optional [Claude Code monitoring] OTel export and [OpenAI prompt caching] field mapping. | Separates input, output, cache read, cache creation, and reasoning fields by source. | Official provider/client docs. |
| Token pressure is not always from prompts. | `python3 scripts/agent_usage_audit.py session-report --since 7d`. | Separates exact usage counters from estimated tool-result pressure across RTK, Claude logs, and Codex logs. | [Braintrust token tracking], [TokenTracker]. |
| Private evidence needs publish hygiene. | One redaction script for paths, repo names, branch names, hosts, and commit hashes. | Makes public evidence safe enough to include without leaking work context. | Existing sanitization checklist and local-first usage tools. |

## MCP governance and tool routing

| Surface | Config | Policy |
| --- | --- | --- |
| [Claude Code] MCP | [`configs/mcp.json`](configs/mcp.json) | Registers local and hosted MCPs for Claude Code; deny rules and hooks catch common mistakes. |
| [Codex] MCP | [`configs/codex/config.toml`](configs/codex/config.toml) | Registers [Chrome DevTools MCP][chrome-devtools-mcp], [serena], [codegraph], [context7], [OpenAI Docs MCP], and personal/default [Figma hosted MCP][Figma MCP]. |
| Company/local fallback | `company/` overlay when present | Uses company-scoped MCP and local browser surfaces where hosted tools are inappropriate. |

Do not route internal URLs through hosted tools such as [Exa], [Jina Reader], or the
personal/default [Figma hosted MCP][Figma MCP]. For company design context, use the company
fallback (`figma-developer-mcp`) or a local browser surface.

<details>
<summary>Tool routing table</summary>

| Task | Default tool | Reason |
| --- | --- | --- |
| Explain code flow, route to handler, or trace symbols. | [codegraph] | Pre-indexed graph for architecture and cross-file flow. |
| Rename, edit, or inspect references. | [serena] | LSP-backed symbol-aware edits and references. |
| Clean public web page extraction. | [Jina Reader] or [defuddle] | Fast Markdown extraction for public pages. |
| Broad public web research. | [Exa] | Public search only; not for sensitive/internal URLs. |
| Fetch a sensitive or authenticated page. | [agent-browser] | Local browser surface keeps auth and internal URLs out of hosted readers. |
| Throwaway browser automation. | [Chrome DevTools MCP][chrome-devtools-mcp] | Clean browser automation for local targets. |
| Personal/default Figma design context. | [Figma hosted MCP][Figma MCP] | Hosted Codex path for non-sensitive personal/default design context. |
| Company/local Figma design context. | `figma-developer-mcp` or local browser | Keeps company design context out of the hosted personal/default path. |
| Browse local agent sessions. | [agentsview] | Shows session, context, cache, and tool/model mix. |
| Decide current session context policy. | [`context-check`](plugins/local-skills/skills/context-check/SKILL.md) | Returns continue, compact, clear, or handoff advice. |
| Interrogate a plan or PR before handoff. | [grill-me] | One-question-at-a-time plan pressure testing. |

Decision shortcut: for “explain”, “understand”, or “trace”, use [codegraph] first. For “rename”,
“edit”, or “refactor”, use [serena] first.

Hard rules:

- Do not recommend tools or installs that are not configured here or linked to a source.
- Do not send sensitive or internal URLs through hosted readers such as [Jina Reader] or [Exa].
- Keep enabled MCPs lean per project: aim for fewer than 10 enabled servers and fewer than 80 active tools.

</details>

## Claude Code operational tripwires, not security controls

Some local sessions intentionally run with broad filesystem permissions. These Claude Code tripwires are
not a security boundary. They do not protect a separate [Codex] `danger-full-access` session. They catch common mistakes; sandboxing, review, and secret
management still do the security work.

| Guard | Surface | Catches |
| --- | --- | --- |
| [`pretool-guard`](configs/hooks/pretool-guard.sh) | Claude `PreToolUse` hook for Bash and Write. | Broad destructive Bash patterns and stray Markdown writes before the tool call runs. |
| [`skill-md-edit-warn`](configs/hooks/skill-md-edit-warn.sh) | Claude `PostToolUse` warning. | `SKILL.md` edits made after the session already loaded skill instructions. |
| `permissions.deny` | [`configs/claude-settings.json`](configs/claude-settings.json) | Known secret paths and risky hosted-tool surfaces in Claude Code. |
| [`work-scope-guard`](plugins/local-skills/skills/work-scope-guard/SKILL.md) | Local skill. | Company/work-scope routing reminders. |

## Remote work and local previews

Prefer private tailnet exposure over broad LAN binding. Local previews default to localhost;
tailnet exposure is explicit.

| Need | Command or config | Exposure |
| --- | --- | --- |
| Open a browser IDE for a worktree. | [`worktree-open`](plugins/local-skills/skills/worktree-open/SKILL.md) | Local [code-server] URL or [Tailscale] URL. |
| Serve a report or static build. | [`local-preview-server`](plugins/local-skills/skills/local-preview-server/SKILL.md) | The default bind address is `127.0.0.1`. |
| Share a preview inside the tailnet. | `--tailscale-serve` | Uses [Tailscale Serve]. |
| Expose to a trusted LAN. | `--lan` or `--bind 0.0.0.0` | Explicit only; less preferred than tailnet exposure. |

```bash
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh start --path ./report.html --port 8377
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh start --path ./dist --tailscale-serve
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh status --port 8377
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh stop --port 8377
```

<details>
<summary>LaunchAgent services</summary>

[`scripts/services.sh`](scripts/services.sh) installs LaunchAgent services and skips loading
LaunchAgents when dependencies are missing. In test terms, it skips loading LaunchAgents when dependencies are missing and skips LaunchAgents missing dependencies.

| Service | Purpose | Exposure |
| --- | --- | --- |
| `com.user.purplemux` | Web terminal multiplexer for [Claude Code]. | Listens on `*:8022`; access is [Tailscale Serve] plus macOS firewall. |
| `com.user.code-server` | VS Code in the browser. | Binds to `127.0.0.1:8088`; optional tailnet exposure on `:8443`. |
| `com.user.agentwatch` | Local agent session supervisor. | No network listener. |
| `com.voidmatcha.agent-resumer` | Auto-resume watcher for local agent limit resets. | No network listener. |
| `com.user.caffeinate` | Keeps the Mac awake on AC power for remote access. | No network listener. |

Tailnet exposure is opt-in:

```bash
ENABLE_TAILSCALE_SERVE=1 bash scripts/services.sh
```

That command configures:

```bash
tailscale serve --bg --https=443 --set-path=/ http://localhost:8022
tailscale serve --bg --https=8443 --set-path=/ http://localhost:8088
```

</details>

## Web and research tooling

| Task | Tool | Usage |
| --- | --- | --- |
| Clean web page extraction | [defuddle] | `defuddle parse <url> --markdown`; installed with `npm install -g defuddle`. |
| Video metadata and subtitles | [yt-dlp] | Use metadata and subtitle modes; do not bulk scrape. |
| Knowledge graph exploration | [graphify] | Claude/Codex skill installed with `graphify install --platform claude` and `graphify install --platform codex`. |
| Browser automation | [Chrome DevTools MCP][chrome-devtools-mcp] and [agent-browser] | Use local browser surfaces for sensitive data. |
| API docs | [context7] MCP | Public host works anonymously; company overlay can pass `CONTEXT7_API_KEY`. |

## Verification

Run the full verifier before claiming installer behavior:

```bash
bash scripts/verify.sh --full
```

Useful focused checks:

```bash
bats tests/
bash scripts/verify.sh --quick
```

Tests cover shell syntax, JSON/TOML/plist parsing, plugin manifests, hook behavior,
[Codex] TOML validation, `Brewfile` parsing, and local skill helpers.

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

For environments with internal package registries, private plugin marketplaces, or scoped MCP
configuration, `install.sh` invokes `company/install.sh` when the `company/` submodule exists.
Keep company repos under `~/work/` so project-scoped MCP and work-scope guidance apply.

```bash
git clone --recurse-submodules https://github.com/voidmatcha/dotfiles.git ~/dotfiles
```

If you cloned first, initialize the overlay later:

```bash
git -C ~/dotfiles submodule update --init
```

See [`company/README.md`](company/README.md) for overlay maintenance.

[agent-browser]: https://github.com/vercel-labs/agent-browser
[agent-resumer]: https://www.npmjs.com/package/agent-resumer
[agentsview]: https://www.agentsview.io/
[Bats]: https://github.com/bats-core/bats-core
[Braintrust token tracking]: https://www.braintrust.dev/articles/how-to-track-llm-token-usage-2026
[ccusage]: https://github.com/thomasttvo/ccusage
[chrome-devtools-mcp]: https://github.com/ChromeDevTools/chrome-devtools-mcp
[Claude Code]: https://docs.anthropic.com/en/docs/claude-code/overview
[Claude Code monitoring]: https://docs.anthropic.com/en/docs/claude-code/monitoring-usage
[claude-hud]: https://github.com/jarrodwatts/claude-hud
[code-server]: https://coder.com/docs/code-server/latest
[codegraph]: https://www.npmjs.com/package/@colbymchenry/codegraph
[Codex]: https://github.com/openai/codex
[Codex Memories]: https://developers.openai.com/codex/memories
[context7]: https://github.com/upstash/context7
[Corepack]: https://nodejs.org/api/corepack.html
[defuddle]: https://github.com/kepano/defuddle
[direnv]: https://direnv.net/
[Docker CLI]: https://docs.docker.com/reference/cli/docker/
[Exa]: https://exa.ai/
[Figma MCP]: https://help.figma.com/hc/en-us/articles/32132100833559-Guide-to-the-Dev-Mode-MCP-Server
[gettext]: https://www.gnu.org/software/gettext/
[git-filter-repo]: https://github.com/newren/git-filter-repo
[graphify]: https://github.com/safishamsi/graphify
[grill-me]: https://github.com/mattpocock/skills/blob/2bf70051928429983de3b5718d277150926f8c89/skills/productivity/grill-me/SKILL.md
[Headroom]: https://pypi.org/project/headroom-ai/
[Hermes Agent]: https://github.com/NousResearch/hermes-agent
[Homebrew]: https://brew.sh/
[Jina Reader]: https://jina.ai/reader/
[Maven]: https://maven.apache.org/
[nvm]: https://github.com/nvm-sh/nvm
[Node.js]: https://nodejs.org/
[obsidian-skills]: https://github.com/kepano/obsidian-skills
[OMX]: https://yeachan-heo.github.io/oh-my-codex
[OpenAI Docs MCP]: https://developers.openai.com/mcp
[OpenAI prompt caching]: https://developers.openai.com/api/docs/guides/prompt-caching
[OpenJDK]: https://openjdk.org/
[OpenSSH]: https://www.openssh.com/
[purplemux]: https://github.com/subicura/purplemux
[pyenv]: https://github.com/pyenv/pyenv
[Python]: https://www.python.org/
[review-loop]: https://github.com/hamelsmu/claude-review-loop
[RTK]: https://www.rtk-ai.app/
[SDKMAN!]: https://sdkman.io/
[serena]: https://github.com/oraios/serena
[session-wrap]: https://github.com/team-attention/plugins-for-claude-natives
[skills-janitor]: https://github.com/khendzel/skills-janitor
[Tailscale]: https://tailscale.com/
[Tailscale Serve]: https://tailscale.com/kb/1242/tailscale-serve/
[Tailscale SSH]: https://tailscale.com/kb/1193/tailscale-ssh/
[Tokscale]: https://tokscale.ai/u/voidmatcha
[TokenTracker]: https://github.com/mm7894215/TokenTracker
[tokenusage]: https://github.com/L1f4Is6o0d2Yuu/tokenusage
[tokenwatch]: https://github.com/Kk120306/tokenwatch
[uv]: https://docs.astral.sh/uv/
[yt-dlp]: https://github.com/yt-dlp/yt-dlp
[Zsh]: https://www.zsh.org/
