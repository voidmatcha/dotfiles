# dotfiles

A reproducible macOS setup for AI-assisted development. The scripts install tools; the repo documents the operating model around them: one shared agent contract, explicit MCP/tool surfaces, measured token behavior, private remote access, and tests for the workflow code itself.

The cost model behind the repo: optimize what enters context, keep cache prefixes stable, and hand off long sessions before carrying context costs more than reuse is worth.

## Design at a glance

| Design choice | What it does | Evidence |
| --- | --- | --- |
| Shared agent contract | [Claude Code], [Codex], and [OMX] route through one AGENTS.md contract instead of separate rulebooks | [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/config.toml`](configs/codex/config.toml), [`configs/AGENTS.md`](configs/AGENTS.md) |
| Explicit tool surfaces | MCP servers, hosted readers, and destructive-command tripwires are documented instead of ambient | [`configs/mcp.json`](configs/mcp.json), [`configs/codex/config.toml`](configs/codex/config.toml), [`configs/hooks/pretool-guard.sh`](configs/hooks/pretool-guard.sh) |
| Tool-output compression | [RTK] compresses noisy shell output before it becomes transcript context | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml), `rtk gain --history` |
| Session lifecycle checks | Local skills make continue, compact, clear, handoff, preview, and verify decisions repeatable | [`plugins/local-skills/skills`](plugins/local-skills/skills) |
| Private remote access | Local previews and browser IDEs default local, then use [Tailscale Serve] when exposure is intentional | [`scripts/services.sh`](scripts/services.sh), [`plugins/local-skills/skills/local-preview-server/SKILL.md`](plugins/local-skills/skills/local-preview-server/SKILL.md) |

Current measured snapshot:

| Signal | Latest value | Source |
| --- | ---: | --- |
| Reuse multiple | about 40.8× | [Tokscale] Cache Read divided by Cache Write |
| New-content share | about 3.4% | [Tokscale] Input plus Cache Write divided by total tokens |
| [RTK] tool-output compression | about 65.3% across two machine [RTK] histories | `rtk gain --history` exports below |

The [RTK] percentage is a tool-output compression metric, not a total-spend reduction. Cache Read share is dashboard context, not a personal efficiency score. [agent-browser] is a qualitative token-pressure control, not a numeric savings claim: it keeps authenticated browsing local and avoids turning whole pages into transcript text when a targeted browser observation is enough.

## What this repo demonstrates

| Signal | What it shows |
| --- | --- |
| Measurement discipline | Token claims are scoped to their source and paired with explicit do-not-claim boundaries |
| Systems thinking | [Claude Code], [Codex], and [OMX] share prompt contracts while keeping each tool's native workflow |
| Cost-aware design | [RTK], [Headroom], [agent-browser], cache-prefix discipline, and lifecycle checks target places where repeated context cost appears |
| Operational tripwires | High-permission local modes stay available; checks catch common mistakes but are not security controls |
| Developer experience | Local skills encode repeat decisions so sessions do not depend on human recall or ad-hoc prompts |
| Verification culture | `scripts/verify.sh --full` and [Bats] cover installers, config, hooks, plugins, and helper behavior |

<details>
<summary>How to read the token numbers</summary>

Quantitative claims in this README come from [Tokscale] or from explicit `rtk gain --history` exports. Derived claims stay scoped to those sources; total-spend attribution is intentionally not stated without a matched control run.

[Tokscale] source captured on 2026-06-17.

| [Tokscale] category | Share | Tokens |
| --- | ---: | ---: |
| Input | 1.0% | 727.5M |
| Output | 0.4% | 276.2M |
| Cache Read | 96.2% | 69.4B |
| Cache Write | 2.4% | 1.7B |
| Reasoning | 0.02% | 16.8M |

[Tokscale] window: 72.108946182B total tokens, $50,017.9449 total cost, 9,344 sessions, 185 active days, date range 2025-09-21 to 2026-06-17.

| [RTK] export | Commands | Raw output | Delivered output | Saved | Compression |
| --- | ---: | ---: | ---: | ---: | ---: |
| Machine A [RTK] history | 26,092 | 101.4M | 27.9M | 73.6M | 72.6% |
| Machine B [RTK] history | 103,434 | 96.1M | 40.9M | 55.4M | 57.6% |
| Combined cross-machine snapshot | 129,526 | 197.5M | 68.8M | about 129.0M | about 65.3% |

Combined [RTK] compression is weighted by raw output: `(73.6M + 55.4M) / (101.4M + 96.1M)`, not the average of `72.6%` and `57.6%`.

Safe claims:

- `about 40.8× reuse`
- `about 3.4% new-content share`
- `about 65.3% RTK tool-output compression across two machine histories`
- `Cache Read about 96.2%`

Do not claim:

- `65.3% cost reduction`
- `96.2% efficiency`
- any exact total-spend contribution from [RTK] without a matched control run
- `optimal`, `minimized`, or best-possible cost

Open measurement items:

- Treat the combined [RTK] row as a cross-machine snapshot from two history exports, not a central deduplicated database total.
- Track [RTK] bypass rate to show compression did not cause reruns or information loss.
- Align [Tokscale] and [RTK] windows before computing any total-spend attribution.

</details>

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

`bootstrap.sh` installs Xcode Command Line Tools when `git` is missing, clones this repo into `~/dotfiles`, and hands off to `./install.sh`. The `company/` overlay runs only when the submodule exists locally.

## What gets installed

| Area | Result | Source |
| --- | --- | --- |
| macOS defaults | Dock, Finder, keyboard, screenshots, firewall, Touch ID sudo | [`scripts/macos.sh`](scripts/macos.sh) |
| CLI packages | [Homebrew] tools, [Bats], [uv], [gettext], [git-filter-repo], [Docker CLI] | [`Brewfile`](Brewfile) |
| Language runtimes | [nvm], [Node.js] LTS, [Corepack], [pyenv], latest [Python] 3, [SDKMAN!], [OpenJDK] LTS, [Maven] | [`scripts/dev.sh`](scripts/dev.sh) |
| Shell and Git | [Zsh] plugins, [direnv], personal/work Git identities, SSH signing via [OpenSSH] | [`scripts/shell.sh`](scripts/shell.sh), [`scripts/git.sh`](scripts/git.sh) |
| Agent CLIs | [Claude Code], [Codex], [Hermes Agent], [OMX], [agent-resumer] | [`scripts/claude.sh`](scripts/claude.sh), [`scripts/codex.sh`](scripts/codex.sh), [`scripts/hermes.sh`](scripts/hermes.sh), [`scripts/dev.sh`](scripts/dev.sh) |
| Remote access | [Tailscale] (including [Tailscale SSH][Tailscale]), [OpenSSH], [code-server], [purplemux] | [`scripts/tailscale.sh`](scripts/tailscale.sh), [`scripts/services.sh`](scripts/services.sh) |

Run one focused installer when you do not want the full setup:

```bash
./scripts/brew.sh
./scripts/macos.sh
./scripts/dev.sh
./scripts/shell.sh
./scripts/git.sh
./scripts/codex.sh
```

## Agent layer

The point is not to make [Claude Code] and [Codex] identical. It is to keep policies, skills, and MCP routing consistent while each tool keeps its native workflow.

| Surface | Role | Source |
| --- | --- | --- |
| [Claude Code] | [Claude Code] execution with shared AGENTS.md rules, hooks, MCP, and [RTK] policy | [`scripts/claude.sh`](scripts/claude.sh), [`configs/CLAUDE.md`](configs/CLAUDE.md) |
| [Codex (with OMX)][Codex] | [Codex] plus [OMX] workflows, goals, and native subagents | [`scripts/codex.sh`](scripts/codex.sh), [`configs/codex/config.toml`](configs/codex/config.toml) |
| [Headroom] | Optional `claudeh`, `codexh`, and `omxh` wrappers for reversible compression and cache-aware routing | [`scripts/headroom-agent.sh`](scripts/headroom-agent.sh), [`scripts/headroom.sh`](scripts/headroom.sh) |
| [agent-resumer] | Pane-aware auto-resume supervisor for Claude/Codex/OMX/OpenCode usage-limit resets | [`scripts/dev.sh`](scripts/dev.sh), [`scripts/services.sh`](scripts/services.sh) |
| [RTK] | Command-output compression policy before noisy shell output enters context | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml) |
| Local skills | Repo-owned procedures for context pressure, handoff, verification, previews, cleanup, and provenance | [`plugins/local-skills/skills`](plugins/local-skills/skills) |

<details>
<summary><a href="https://docs.anthropic.com/en/docs/claude-code/overview">Claude Code</a> wiring</summary>

| Piece | Source | What it contributes |
| --- | --- | --- |
| Shared prompt contract | [`configs/CLAUDE.md`](configs/CLAUDE.md) | imports ~/.agent/AGENTS.md through `@~/.agent/AGENTS.md` and imports `@RTK.md` |
| Settings | [`configs/claude-settings.json`](configs/claude-settings.json) | Installs hooks, status line, permissions, plugins, and MCP config references |
| MCP surface | [`configs/mcp.json`](configs/mcp.json) | Keeps approved servers explicit |
| Local agents | [`configs/agents`](configs/agents) | Provides role prompts shared by [Claude Code] setup |

Installed [Claude Code] plugins include [`claude-hud@claude-hud`][claude-hud], [`skills-janitor@skills-janitor`][skills-janitor], [`review-loop@hamel-review`][review-loop], [`local-skills@dotfiles-local`](plugins/local-skills), [`session-wrap`][session-wrap], and [`obsidian-skills`][obsidian-skills].

</details>

<details>
<summary><a href="https://github.com/openai/codex">Codex</a> and <a href="https://yeachan-heo.github.io/oh-my-codex">OMX</a> wiring</summary>

| Piece | Source | What it contributes |
| --- | --- | --- |
| Installer | [`scripts/codex.sh`](scripts/codex.sh) | Installs `@openai/codex`, `oh-my-codex`, and writes `~/.codex/config.toml` |
| Prompt contract | [`configs/codex/config.toml`](configs/codex/config.toml) | Sets `developer_instructions` to the [Codex]/[OMX] AGENTS.md contract |
| Skill installer | [`scripts/skills.sh`](scripts/skills.sh) | `scripts/skills.sh codex` installs repo-local [Codex] skills, including `dotfiles-verify` |
| Goals | [`configs/codex/config.toml`](configs/codex/config.toml) | Keeps `[features] goals = true` enabled |
| Memories | [`configs/codex/config.toml`](configs/codex/config.toml) | Enables [Codex Memories] with local recall and excludes external-context sessions from memory generation |
| MCP | [`configs/codex/config.toml`](configs/codex/config.toml) | `mcp_servers` covers [Chrome DevTools MCP][chrome-devtools-mcp], [serena], [codegraph], [context7], [OpenAI Docs MCP], and personal/default [Figma hosted MCP][Figma MCP]. Company Figma context is separate: the company overlay uses `figma-developer-mcp` and disables hosted Codex Figma by default |

Skills are procedural workflows under `.codex/skills`; native subagents are role files under `.codex/agents`. Hosted [Codex] MCP entries stay disabled unless the company overlay explicitly enables them.

</details>

## Local skills: recurring decisions

The local skills exist because these choices kept recurring: whether to continue a long session, how to hand off work, how to preview generated files privately, how to verify dotfiles changes, and how to keep imported workflow assets traceable. Encoding them as skills keeps the decision path visible and repeatable.

| Decision | Skill | Result |
| --- | --- | --- |
| Continue, compact, clear, or hand off? | [`context-check`](plugins/local-skills/skills/context-check/SKILL.md) | Reads context, cache, idle, and headroom signals before recommending an action |
| Move work to a fresh [Claude Code], [Codex], or [OMX] session? | [`handover`](plugins/local-skills/skills/handover/SKILL.md) | Writes handshake artifacts instead of relying on a pasted summary |
| Claim an installer/config change is safe? | [`dotfiles-verify`](plugins/local-skills/skills/dotfiles-verify/SKILL.md) | Runs the repo verifier and [Bats] gate |
| View generated output from another device? | [`local-preview-server`](plugins/local-skills/skills/local-preview-server/SKILL.md) | Defaults to localhost and uses [Tailscale Serve] only when requested |
| Open a worktree in the browser IDE? | [`worktree-open`](plugins/local-skills/skills/worktree-open/SKILL.md) | Resolves local and [Tailscale] [code-server] URLs consistently |
| Clean up stuck agent processes? | [`agent-reap`](plugins/local-skills/skills/agent-reap/SKILL.md) | Scans conservatively and requires explicit approval before killing |
| Prune agents, commands, skills, or MCPs? | [`agent-usage-audit`](plugins/local-skills/skills/agent-usage-audit/SKILL.md) | Grounds pruning decisions in usage data |
| Diagnose stale code intelligence? | [`code-intel-doctor`](plugins/local-skills/skills/code-intel-doctor/SKILL.md) | Checks MCP config, installed tools, and repo index health |
| Avoid sending work data through the wrong surface? | [`work-scope-guard`](plugins/local-skills/skills/work-scope-guard/SKILL.md) | Keeps sensitive routing reminders fail-open and generic |
| Track imported workflow assets? | [`source-provenance`](plugins/local-skills/skills/source-provenance/SKILL.md) | Records source, license, and local modifications |
| Run a long handoff in cmux? | [`cmux-handoff-runner`](plugins/local-skills/skills/cmux-handoff-runner/SKILL.md) | Starts, polls, and recovers long [Claude Code]/[Codex]/[OMX] handoffs |

`handover` produces the transferable state. `cmux-handoff-runner` is the terminal runner around that state: it preflights the pane, starts the session, watches for idle/stuck behavior, and records recovery markers.

## Token-efficiency design

This setup targets token cost at five points: what enters context, whether cache prefixes stay stable, how long idle sessions wait, when a session should hand off, and whether optimizations are measured.

| Cost mechanism | Repo mechanism | Evidence |
| --- | --- | --- |
| Context ingress | [RTK] compresses noisy command output before transcript ingress | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml), `rtk gain --history` |
| Cache prefix stability | [Claude Code] keeps a compact `CLAUDE.md`; [Codex] keeps one `developer_instructions` contract and explicit MCP entries | [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/codex/config.toml`](configs/codex/config.toml) |
| Idle and context pressure | `context-check` reads idle, prompt, transcript, and [Headroom] pressure before recommending continue, compact, clear, or handoff | [`plugins/local-skills/skills/context-check/SKILL.md`](plugins/local-skills/skills/context-check/SKILL.md) |
| Long-session handoff | `handover` carries distilled state into fresh [Claude Code], [Codex], or [OMX] sessions | [`plugins/local-skills/skills/handover/SKILL.md`](plugins/local-skills/skills/handover/SKILL.md) |
| Survival under real work | Hook failure paths and bypasses are tested; the verifier covers hooks and skill helpers | [`configs/hooks`](configs/hooks), [`tests/scripts.bats`](tests/scripts.bats), [`scripts/verify.sh`](scripts/verify.sh) |

Only [RTK] and [Tokscale] get numeric claims. Everything else is a control, not a measured savings claim:

- [Headroom] and `context-check` decide when long sessions should continue, compact, clear, or hand off.
- [codegraph] and [serena] keep code lookup narrow.
- [agent-browser], [Jina Reader], and [defuddle] avoid full page/source dumps when targeted extraction is enough.
- `handover` carries distilled state into a fresh session.
- `local-preview-server` keeps browser artifacts out of chat.

The README does not assign a cost-saving percentage to those controls.

<details>
<summary>Why these five principles matter</summary>

1. **Stateless billing means ingress matters.** A token admitted early can be re-read on later calls. [RTK] reduces the first factor by compressing tool output; search batching reduces the second factor by lowering call count.
2. **Cache is a prefix machine.** Naive compression can break cache prefixes. This repo keeps prefix-forming files stable and uses [Headroom] only as an optional wrapper, not an invisible rewrite layer.
3. **Cache entries expire.** Idle sessions can force repeated cache writes for content that looked reusable. `context-check` makes that pressure visible.
4. **Long sessions are not free.** A high cache-read ratio helps only while reuse beats the cost of carrying context. `handover` exists so clearing context can be deliberate rather than lossy.
5. **Unmeasured optimization is a guess.** [RTK] gain, [Tokscale] summaries, [Bats], and `scripts/verify.sh` keep the efficiency layer tied to evidence.

`about 65.3%` is a weighted tool-output compression claim across two machine [RTK] histories, not a total-cost claim.

</details>

## MCP governance and tool routing

| Surface | Config | Policy |
| --- | --- | --- |
| [Claude Code] MCP | [`configs/mcp.json`](configs/mcp.json) | `permissions.deny` blocks risky paths and hosted-sensitive routes |
| [Codex] MCP | [`configs/codex/config.toml`](configs/codex/config.toml) | `mcp_servers` covers [Chrome DevTools MCP][chrome-devtools-mcp], [serena], [codegraph], [context7], [OpenAI Docs MCP], and personal/default [Figma hosted MCP][Figma MCP]. Company Figma context is separate: the company overlay uses `figma-developer-mcp` and disables hosted Codex Figma by default |
| Company overlay | [`company/install.sh`](company/install.sh) | Hosted [Codex] MCPs require explicit opt-in |

Do not route internal URLs through hosted tools such as [Exa], [Jina Reader], or the personal/default [Figma hosted MCP][Figma MCP]. For company design context, use the company overlay's `figma-developer-mcp` or a local browser surface.

<details>
<summary>Tool routing reference</summary>

| Need | Tool | Why |
| --- | --- | --- |
| Explain code flow, route to handler, or trace symbols | [codegraph] | Pre-indexed code graph for architecture and call-path questions |
| Rename, edit, or inspect references | [serena] | LSP-backed code intelligence and symbol-aware edits |
| Clean public web page extraction | [Jina Reader] | Fast Markdown extraction for public pages |
| Broad public web research | [Exa] | External search when local/repo evidence is not enough |
| Fetch a sensitive or authenticated page | [agent-browser] with local Chrome profile | Keeps auth and internal URLs local, and avoids dumping full page/source text when a targeted browser observation is enough |
| Throwaway browser automation | [Chrome DevTools MCP][chrome-devtools-mcp] | Clean browser session without auth carryover |
| API or framework docs | [context7] MCP or [OpenAI Docs MCP] | Versioned docs are better than memory |
| [Figma][Figma MCP] design context | [Figma MCP] | Personal/default [Codex]/[OMX] can use hosted [Figma][Figma MCP] context. Company design context is a separate path through the company overlay's `figma-developer-mcp`; hosted Codex Figma is disabled there by default |
| Browse [Claude Code], [Codex], or local agent sessions | [agentsview] | Shows duration, peak context, cache economics, tool/model mix, and session spikes |
| Current session context/cache policy | [`context-check`](plugins/local-skills/skills/context-check/SKILL.md) | Returns continue, compact, clear, or handoff advice |
| Plan or PR interrogation before handoff | [grill-me] | Runs one-question-at-a-time interrogation with recommended answers |

Decision shortcut: for “explain”, “understand”, or “trace”, use [codegraph] first. For “rename”, “edit”, or “refactor”, use [serena] first.

Hard rules:

- Do not recommend tools or installs that are not configured here or linked to a source.
- Do not send sensitive or internal URLs through hosted readers such as [Jina Reader] or [Exa].
- Do not bulk-scrape X, Reddit, LinkedIn, [Jina Reader], or [Exa].
- Keep enabled MCPs lean per project: aim for fewer than 10 enabled servers and fewer than 80 active tools.
- Do not create stray top-level Markdown files without explicit request.

</details>

## Claude Code operational tripwires, not security controls

Some local sessions run with broad filesystem permissions. These checks are Claude Code tripwires, not a security boundary, and they do not protect a separate [Codex] `danger-full-access` session. They catch common mistakes; sandboxing, review, and secret management still do the security work.

| Tripwire | Scope | What it catches |
| --- | --- | --- |
| `permissions.deny` in [`configs/claude-settings.json`](configs/claude-settings.json) | Claude permission deny list | Secret-like reads and hosted-sensitive routes: `.env*`, `secrets/**`, `WebFetch`, `mcp__filesystem` |
| [`pretool-guard`](configs/hooks/pretool-guard.sh) | Claude `PreToolUse` hook for Bash and Write | Broad destructive Bash patterns and stray Markdown writes before the tool call runs |
| [`skill-md-edit-warn`](configs/hooks/skill-md-edit-warn.sh) | Claude `PostToolUse` warning | `SKILL.md` edits made after the session already loaded skill instructions |

## Remote work and local previews

Prefer private tailnet exposure over broad LAN binding for remote work. Local previews default to localhost; tailnet exposure is explicit.

Use [`worktree-open`](plugins/local-skills/skills/worktree-open/SKILL.md) to build [code-server] URLs for one worktree or all worktrees in a repo. It prefers the [Tailscale Serve] endpoint at `https://<tailnet-host-or-ip>:8443`, then falls back to the local [code-server] URL.

Use [`local-preview-server`](plugins/local-skills/skills/local-preview-server/SKILL.md) for generated HTML reports, static build outputs, exported dashboards, and other local browser artifacts. The default bind address is `127.0.0.1`. Use `--tailscale-serve` when the preview should be reachable from another device on the tailnet. Use `--lan` or `--bind 0.0.0.0` only when trusted LAN exposure is intentional.

```bash
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh start --path ./report.html --port 8377
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh start --path ./dist --tailscale-serve
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh status --port 8377
plugins/local-skills/skills/local-preview-server/scripts/local-preview-server.sh stop --port 8377
```

<details>
<summary>LaunchAgent services</summary>

[`scripts/services.sh`](scripts/services.sh) installs LaunchAgent services and skips loading LaunchAgents when dependencies are missing.

| Service | Purpose | Exposure |
| --- | --- | --- |
| `com.user.purplemux` | Web terminal multiplexer for [Claude Code] | Listens on `*:8022`; access is [Tailscale Serve] plus macOS firewall |
| `com.user.code-server` | VS Code in the browser | Binds to `127.0.0.1:8088`; optional tailnet exposure on `:8443` |
| `com.user.agentwatch` | Local agent session supervisor | No network listener |
| `com.voidmatcha.agent-resumer` | Auto-resume watcher for local agent limit resets | No network listener |
| `com.user.caffeinate` | Keeps the Mac awake on AC power for remote access | No network listener |

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
| Clean web page extraction | [defuddle] | `defuddle parse <url> --markdown`; installed with `npm install -g defuddle` |
| Video metadata and subtitles | [yt-dlp] | Use metadata and subtitle modes, not bulk scraping |
| Knowledge graph exploration | [graphify] | Claude/Codex skill for [Claude Code] and [Codex], installed with `graphify install --platform claude` and `graphify install --platform codex` |
| Browser automation | [Chrome DevTools MCP][chrome-devtools-mcp] and [agent-browser] | Use local browser surfaces for sensitive data |
| API docs | [context7] MCP | Public host works anonymously; company overlay passes `CONTEXT7_API_KEY` for authenticated use |

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

Tests cover shell syntax, JSON/TOML/plist parsing, plugin manifests, hook behavior, [Codex] TOML validation, `Brewfile` parsing, and local skill helpers.

## Repository map

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

For environments with internal package registries, private plugin marketplaces, or scoped MCP configuration, `install.sh` invokes `company/install.sh` when the `company/` submodule exists. Keep company repos under `~/work/` so project-scoped MCP and work-scope guidance apply.

Clone with overlay:

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
[chrome-devtools-mcp]: https://github.com/ChromeDevTools/chrome-devtools-mcp
[Claude Code]: https://docs.anthropic.com/en/docs/claude-code/overview
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
[Tokscale]: https://tokscale.ai/u/voidmatcha
[uv]: https://docs.astral.sh/uv/
[yt-dlp]: https://github.com/yt-dlp/yt-dlp
[Zsh]: https://www.zsh.org/
