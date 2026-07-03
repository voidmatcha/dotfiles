# dotfiles

macOS setup for AI coding assistants — [Claude Code], [Codex], and [OMX] — under
one shared rule set, with installer behavior and token-efficiency claims measured
instead of guessed.

Most dotfiles pile up config. This repo treats the agent layer as production
tooling: one plain-text `AGENTS.md` contract governs the assistants, local
verification covers 162 Bats checks, and non-trivial commits record rejected
alternatives in Lore trailers (`git log --grep='Rejected:'`).

Current headline: local measurements show the setup is **cache-heavy and
tool-output aware**, not magically cheaper. On 2026-06-29, [RTK] removed 25.2M
estimated command-output tokens before transcript ingress globally (57.3%; 69.1%
inside this repo), [Headroom] reported 97.9% cached requests with zero
failed/rate-limited/cache-bust-token-lost counters, and `ccusage` showed a 94.0%
cache-read share over the last ten local days.

## What to review first

| Reviewer question | Start | What it proves |
| --- | --- | --- |
| Are [Claude Code], [Codex], and [OMX] governed by one contract? | [`configs/AGENTS.md`](configs/AGENTS.md), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/config.toml`](configs/codex/config.toml) | One policy layer exists while each tool keeps its native workflow. |
| Are token-efficiency claims measured? | [Evidence ledger](#evidence-ledger), [`configs/RTK.md`](configs/RTK.md), `rtk gain --history`, [Headroom] `/metrics`, `ccusage` | Each number has a source, scope, and boundary; the README does not add unlike counters together. |
| Are hosted and local tools separated? | [`configs/mcp.json`](configs/mcp.json), [`configs/codex/config.toml`](configs/codex/config.toml), [`configs/hooks/pretool-guard.sh`](configs/hooks/pretool-guard.sh) | Hosted readers, browser surfaces, local MCPs, and destructive-command tripwires are routed explicitly. |
| Can setup changes be verified? | [`scripts/verify.sh`](scripts/verify.sh), [`tests/scripts.bats`](tests/scripts.bats), [`lefthook.yml`](lefthook.yml) | Installer, hook, config, plugin, skill, secret-scan, and doctor behavior are testable. |
| Can local work be previewed without broad exposure? | [`scripts/services.sh`](scripts/services.sh), [`plugins/local-skills/skills/local-preview-server/SKILL.md`](plugins/local-skills/skills/local-preview-server/SKILL.md) | Previews default to localhost and use [Tailscale Serve] only when remote access is intentional. |

## Design at a glance

| Design choice | What it does | Evidence |
| --- | --- | --- |
| Shared agent contract | Routes [Claude Code], [Codex], and [OMX] through one `AGENTS.md` contract. | [`configs/AGENTS.md`](configs/AGENTS.md), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/config.toml`](configs/codex/config.toml) |
| Explicit tool surfaces | Documents MCP servers, hosted readers, browser surfaces, and destructive-command guards. | [`configs/mcp.json`](configs/mcp.json), [`configs/codex/config.toml`](configs/codex/config.toml), [`configs/hooks/pretool-guard.sh`](configs/hooks/pretool-guard.sh) |
| Tool-output compression | Uses [RTK] before noisy shell output becomes transcript context. | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml), `rtk gain --history` |
| Proxy/cache telemetry | Tracks routed request health, cache reuse, and optimization counters separately from usage-cost logs. | [`scripts/headroom.sh`](scripts/headroom.sh), [`scripts/headroom-agent.sh`](scripts/headroom-agent.sh), [Headroom] `/metrics` |
| Local skill layer | Keeps high-risk workflows explicit: context checks, handoff, preview, audit, reach, reap, and provenance. | [`plugins/local-skills/skills`](plugins/local-skills/skills) |
| Verification culture | Treats dotfiles automation like production code. | [`scripts/verify.sh`](scripts/verify.sh), [`scripts/doctor.sh`](scripts/doctor.sh), [`scripts/secret-scan.sh`](scripts/secret-scan.sh), [`tests/`](tests/) |

## Evidence ledger

These numbers are measurement surfaces, not one additive savings total. They are
local snapshots and will drift as commands and sessions run.

### Current local snapshot

Captured 2026-06-29 in Asia/Seoul.

| Surface | Window / scope | What it measures | Result |
| --- | --- | --- | --- |
| [RTK] global | `rtk gain --history --format json` | Estimated command/tool output removed before transcript ingress. | 22,345 commands; 44.0M raw estimate → 18.8M delivered estimate; 25.2M removed (57.3%). |
| [RTK] project | `rtk gain --history --project --format json` in this repo | Same metric, scoped to `/Users/user/work/dotfiles`. | 1,481 commands; 1.54M raw estimate → 482.6K delivered estimate; 1.07M removed (69.1%). |
| [Headroom] proxy | Current proxy lifetime `/metrics` | Routed LLM proxy counters: cache/request health and optimization savings. | 13,676 requests; 13,385 cached (97.9%); 1.567B input tokens; 4.60M output tokens; 288.3M tokens saved; 0 failed, rate-limited, cache-bust, or cache-bust-token-lost counters. |
| [ccusage] | `ccusage daily -j --offline --since 2026-06-20 --timezone Asia/Seoul` | Local Claude/Codex log estimate for usage mix and spend. | 10 days; 5.029B total tokens; 4.728B cache-read tokens (94.0%); 6.0% non-cache-read share; $4,536.65 estimated cost. |

### Historical / public reference

| Surface | Window / scope | Result | Use |
| --- | --- | --- | --- |
| [Tokscale] public snapshot | 2025-09-21 through 2026-06-17 | 72.109B total tokens; 96.2% cache-read share; $50,017.94 dashboard cost. | Shareable historical token-mix context, not causality proof for any one repo change. |
| [RTK] cross-machine export | Older two-machine command histories | 129,526 commands; 197.5M raw estimate → 68.8M delivered estimate; about 129.0M removed (about 65.3%). | Historical compression context. The current local snapshot above is the headline for this repo. |

### Measurement boundaries

| Surface | Safe interpretation | Boundary |
| --- | --- | --- |
| [RTK] | Reduces command/tool output before the assistant reads it. | Not a cost-reduction percentage without a matched no-RTK baseline. |
| [Headroom] | Shows health and optimization counters for traffic routed through the proxy. | Lifetime proxy counters, not period-aligned with `ccusage`; internal `tokens_saved` is not additive with RTK. |
| [ccusage] | Estimates token mix, cache-read share, and spend from local logs. | Useful for usage accounting, not a causal optimization proof by itself. |
| [Tokscale] | Public historical token-mix snapshot. | Snapshot window and data source differ from current local commands. |

Safe claims:

- [RTK] is removing substantial noisy shell output before transcript ingress.
- [Headroom] looks healthy in the current proxy lifetime: high cached-request share,
  zero failed/rate-limited counters, and zero cache-bust-token-lost counter.
- Recent `ccusage` logs are cache-heavy: 94.0% cache-read share, about 6.0%
  non-cache-read share.
- The combined story is layer-by-layer: less tool output admitted, stable cache-heavy
  sessions, and local usage ledgers.

Do not claim:

- `RTK saved + Headroom saved + cache read = total savings`.
- `57.3%` or `69.1%` RTK compression equals cost reduction.
- `97.9% cached requests` or `94.0% cache-read share` proves optimal efficiency.
- exact spend avoided without a matched baseline and aligned measurement window.

## External research applied

| Source pattern | Takeaway | Local effect |
| --- | --- | --- |
| [OpenAI prompt caching] | Cached-token accounting depends on stable repeated prefixes; static content should come before variable content. | Keep shared AGENTS/CLAUDE/Codex contracts compact and avoid dynamic tool churn in the prefix. |
| [Claude Code monitoring] | Usage, cost, tool activity, cache-read, and cache-creation fields should be exported before making cost claims. | Keep `context-check` advisory and treat OTel/local exports as measurement work, not README slogans. |
| [Braintrust token tracking] | Token tracking is most useful when call-level usage, context pressure, and agent traces are separate. | README separates [Tokscale] mix, [RTK] ingress compression, [Headroom] proxy counters, and [ccusage] local usage logs. |
| [ccusage], [tokenwatch], [tokenusage], [TokenTracker] | Local-first usage tools can export token ledgers without uploading prompts or paths. | `scripts/dev.sh` installs `ccusage`; future public exports need redaction instead of raw prompt sharing. |

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
./update.sh --check   # preview: git pull + install.sh --dry-run --upgrade
./update.sh           # git pull --ff-only + install.sh --upgrade
./update.sh --no-pull # re-run local upgrade steps without pulling
```

Health/status snapshot:

```bash
./scripts/doctor.sh
```

`bootstrap.sh` installs Xcode Command Line Tools when `git` is missing, clones this
repo into `~/dotfiles`, and hands off to `./install.sh`. The `company/` overlay runs
only when the submodule exists locally.

<details>
<summary>What gets installed</summary>

| Area | Installs/configures | Source |
| --- | --- | --- |
| macOS defaults | Dock, Finder, keyboard, screenshots, firewall, Touch ID sudo. | [`scripts/macos.sh`](scripts/macos.sh) |
| CLI packages | [Homebrew] tools, [Bats], [gitleaks], [uv], [gettext], [git-filter-repo], [Docker CLI]. | [`Brewfile`](Brewfile) |
| Language runtimes | [nvm], [Node.js] LTS, [Corepack], [pyenv], latest [Python] 3, [SDKMAN!], [OpenJDK] LTS, [Maven]. | [`scripts/dev.sh`](scripts/dev.sh) |
| Shell and Git | [Zsh] plugins, [direnv], personal/work Git identities, SSH signing via [OpenSSH]. | [`scripts/shell.sh`](scripts/shell.sh), [`scripts/git.sh`](scripts/git.sh) |
| Agent CLIs | [Claude Code], [Codex], [Hermes Agent], [OMX]. | [`scripts/claude.sh`](scripts/claude.sh), [`scripts/codex.sh`](scripts/codex.sh), [`scripts/hermes.sh`](scripts/hermes.sh), [`scripts/dev.sh`](scripts/dev.sh) |
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
| Fact-check an AI answer before trusting or publishing it? | [`verify-output`](plugins/local-skills/skills/verify-output/SKILL.md) | Extracts claims, tries to refute each (plus bounded public fact-check), and classifies supported/unsupported/not-checked. |
| Find the root cause of a bug, regression, or flaky failure? | [`hypothesis-debugging`](plugins/local-skills/skills/hypothesis-debugging/SKILL.md) | Separates facts from assumptions, ranks falsifiable candidates, keeps an attempt log; five-whys quick mode for shallow bugs. |
| About to commit to a costly, hard-to-reverse plan? | [`premortem`](plugins/local-skills/skills/premortem/SKILL.md) | Assume-failure analysis: enumerate failure modes, score likelihood x impact, and fold mitigations back into the plan. |
| Research-improve the repo's own skills, hooks, or scripts? | [`asset-improver`](plugins/local-skills/skills/asset-improver/SKILL.md) | External research plus cross-model verification behind a propose -> approve -> apply gate. |

`handover` owns context/session transfer and long-running agent coordination. `cmux` and
`purplemux` stay display/control backends for workspaces, tabs, surfaces, focus, and terminal health.

## Token-efficiency design

The goal is not one magic percentage. The setup reduces token pressure at
separate layers and keeps their counters separate.

| Layer | Control | Current evidence |
| --- | --- | --- |
| Ingress | [RTK] compresses noisy shell output before it becomes transcript context. | Current project snapshot: 69.1% estimated command-output reduction. |
| Prefix/cache stability | Shared prompt contracts stay compact and stable while tool-specific details live in native configs. | [Headroom] cached-request share is 97.9%; `ccusage` cache-read share is 94.0% over the measured ten-day window. |
| Proxy health | [Headroom] tracks routed request failures, rate limits, cache-busts, and saved-token counters. | Current proxy lifetime: zero failed, rate-limited, cache-bust, or cache-bust-token-lost counters. |
| Usage ledger | [ccusage] and [Tokscale] report token mix and estimated spend separately from optimization counters. | Recent local logs show 5.029B total tokens and $4,536.65 estimated cost for 2026-06-20..2026-06-29. |
| Session lifecycle | `context-check` and `handover` make continue, compact, clear, and transfer decisions explicit. | Local skills keep long sessions from silently accumulating stale context. |

[agent-browser] is a qualitative token-pressure control for targeted browser observation and authenticated browsing, not a numeric savings claim.

[Headroom], `context-check`, `handover`, [agent-browser], [Jina Reader],
[defuddle], [codegraph], and [serena] reduce token pressure by shaping what gets
loaded or carried. This README intentionally does not assign them one shared
savings percentage.

<details>
<summary>Five principles behind the setup</summary>

1. **Stateless billing rewards ingress control.** A token that never enters the
   transcript is not reread on later calls. [RTK] attacks noisy tool output at
   ingress.
2. **Cache is prefix-sensitive.** [OpenAI prompt caching] documents that stable
   repeated prefixes matter. The repo keeps shared prompt contracts compact
   rather than loading every tool surface everywhere.
3. **Cache has a clock and a scope.** High cache-read share helps only while the
   reused context is still useful. `context-check` exists so idle and context
   pressure are visible.
4. **Long sessions are not free.** `handover` makes clearing context deliberate
   instead of lossy.
5. **Unmeasured optimization is a guess.** [RTK] gain, [Headroom] metrics,
   [ccusage], [Tokscale], [Bats], and `scripts/verify.sh` keep efficiency claims
   tied to evidence.

</details>

## Measurement roadmap

These are gaps, not current achievements.

| Gap | Next artifact | Why it matters |
| --- | --- | --- |
| Measurement windows differ across [RTK], [Headroom], [ccusage], and [Tokscale]. | One dated export script that records all available counters in the same run. | Prevents mixing lifetime, ten-day, and historical dashboard numbers as if they were one experiment. |
| [Headroom] output-savings data is not yet populated. | Add a repeatable `headroom output-savings` capture once real data exists. | Separates prompt/input savings from output-token behavior. |
| [RTK] safety still depends on local history inspection. | Privacy-preserving `RTK_HOOK_AUDIT=1` report for fallbacks, bypasses, and repeat-after-compression candidates. | Proves compression did not hide meaningful output or create fragile command behavior. |
| Public dashboards can drift or become stale. | Refresh [agentsview]/[Tokscale]-style snapshots only after a full resync. | Avoids stale public evidence in the headline. |
| Public evidence needs publish hygiene. | Redaction script for paths, repo names, branch names, hosts, and commit hashes. | Makes local usage exports safe to share. |

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
| [`pretool-guard`](configs/hooks/pretool-guard.sh) | Claude `PreToolUse` hook for Bash. | Broad destructive Bash patterns (force push, root rm -rf, dotenv reads, curl-pipe-bash, broad pkill on shared infra) before the tool call runs. |
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
bash scripts/secret-scan.sh --optional
bash scripts/doctor.sh
```

Pre-push protection is managed by [lefthook]: `install.sh` runs `lefthook install`
when available, and `lefthook.yml` runs both `scripts/verify.sh` and required
[gitleaks] secret scanning before push. Install missing hook tooling with
`./scripts/brew.sh`.

Tests cover shell syntax, JSON/TOML/plist parsing, plugin manifests, hook behavior,
[Codex] TOML validation, `Brewfile` parsing, secret-scan wiring, doctor/status
checks, and local skill helpers.

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

[gitleaks]: https://github.com/gitleaks/gitleaks

[lefthook]: https://lefthook.dev/
