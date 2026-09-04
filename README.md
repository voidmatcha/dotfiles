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
| [RTK] ingress reduction | `rtk gain` records command-output reduction estimates. The hook keeps search rewrites and bypasses `cat`/`head`/`tail`, whose default RTK read path returns full content. | Directional tool-output estimate only. Do not report it as realized token or billing savings. |
| Public usage ledger | [Tokscale]: 93.711B tokens and 95.8% cache-read through 2026-07-05. | Public token-mix snapshot. Not causality proof for one repo change. |
| Headroom proxy health *(retired 2026-08)* | 22,337 routed requests. 18,469 cached (82.7%). 54 failed (0.24%). 0 rate-limited. 1 cache-bust. | Measured while the Headroom proxy was in use. It is proxy telemetry, never a token-savings figure — output-token savings were never claimed, because no baseline or holdout run existed. Kept as a record of what was measured; the layer has since been removed. |

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

The default update rerun converges installed package-manager tools and direct
release binaries to the latest release on each configured update channel.
Intentional skill commit pins and the 1.5 GB whisper model are preserved; use
`--setup-only` to skip explicit refreshes of already-installed tools.

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
./scripts/retire.sh
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

Full installs run `scripts/retire.sh` after Homebrew setup. Its append-only
allowlist removes only tools this repository previously installed; broad
package-manager cleanup is intentionally excluded so independently installed
software survives synchronization across machines.

</details>

## Agent layer

The point is not to make [Claude Code] and [Codex] identical. The point is to keep policy, skills, MCP routing, and verification consistent while each tool keeps its native workflow.

Claude imports `@~/.agent/AGENTS.md` through [`configs/CLAUDE.md`](configs/CLAUDE.md). In plain terms, it imports ~/.agent/AGENTS.md.

Codex setup writes `~/.codex/config.toml` from [`configs/codex/config.toml`](configs/codex/config.toml). It enables `[features] goals = true`, keeps `mcp_servers` entries in generated TOML, and installs Codex skills with `scripts/skills.sh codex`.

Heavy model modes stay harness-specific and opt-in: Claude reserves Fable for
its hardest, longest-running work, while Codex reserves Ultra for large tasks
with independently bounded parallel lanes. Neither mode broadens task scope.

| Surface | Role | Source |
| --- | --- | --- |
| [Claude Code] | Claude execution with shared AGENTS.md rules, hooks, MCP, and [RTK] policy. | [`scripts/claude.sh`](scripts/claude.sh), [`configs/CLAUDE.md`](configs/CLAUDE.md), [`configs/claude-settings.json`](configs/claude-settings.json) |
| [Codex] | Codex execution with goals, memories, and native subagents. | [`scripts/codex.sh`](scripts/codex.sh), [`configs/codex/config.toml`](configs/codex/config.toml) |
| [RTK] | Command-output compression before noisy shell output enters context. | [`configs/RTK.md`](configs/RTK.md), [`configs/rtk-config.toml`](configs/rtk-config.toml) |
| Local skills | Repo-owned procedures for context pressure, handoff, verification, previews, cleanup, and provenance. | [`plugins/local-skills/skills`](plugins/local-skills/skills) |
| [llmwiki](#llmwiki) | Work history from both harnesses compiled into one Obsidian vault. | [`scripts/llmwiki`](scripts/llmwiki), [`configs/llmwiki`](configs/llmwiki) |

`ResumerBar`/`agent-resumer` and `cmux-deck` are machine-local runtime
integrations, not components installed or configured by this repository. Do not
commit their generated shims, sockets, state, LaunchAgents, or injected shell
blocks here. The supported `cmux` references below mean the current cmux CLI and
display backend, not the separate `cmux-deck` project.

### llmwiki

Session history lives in per-harness stores that nothing reads together, so
"what did we decide about X" has no answer a month later. llmwiki imports that
history incrementally and compiles it into an Obsidian vault that both Claude
and Codex write into and a human can edit.

| Piece | What it does |
| --- | --- |
| `ingest` | Reads new claude-mem rows into an append-only event log. The live database is copied through SQLite's backup API first, never read while its WAL is active. |
| `compile` | Rewrites vault views from those events, but only between `GEN:` markers. Everything outside them is human-owned and never touched. |
| `search`, `list-open`, `status` | An `rg` wrapper over the vault plus task queries. Deep cross-session search stays with `mem-search`; no embeddings, no vector store. |
| `serve` | Read-only web view of the vault, refreshed without waiting for a compile. It binds `127.0.0.1`; reaching it from another machine needs `ENABLE_TAILSCALE_SERVE=1` at install time, which publishes it on the tailnet only. |
| `snapshot` | Dated backups of vault and event store. The vault is not a pure derivative — hand-written sections exist only there. |
| Hooks | `SessionStart` injects the current project's open tasks (5 tasks, 1,000 chars max) and binds a session named `T-0043` to that task. `UserPromptSubmit` records cwd changes so work can be attributed to a project. Both fail open, and log their failures. |

Claude reads the vault convention from [`configs/AGENTS.md`](configs/AGENTS.md);
Codex gets the same text composed into `~/.codex/AGENTS.md` by
[`scripts/codex.sh`](scripts/codex.sh). Collection, compile, and snapshot run
unattended on a schedule; writing lessons and Library notes is manual and goes
through [`llmwiki-curate`](plugins/local-skills/skills/llmwiki-curate/SKILL.md).

The vault path is configured, not hardcoded — `compile` refuses to run against a
swapped vault without saying what would be lost.

### Installed external skills and plugins

These are installed or enabled in addition to the repo local skills listed below. The `local-skills@dotfiles-local` plugin exposes those local skills to Claude.

| Use case | Item | What it does |
| --- | --- | --- |
| Pressure-test a plan. | [`grill-me`](scripts/skills.sh) | Standalone Claude and Codex skill installed from a pinned upstream ref. |
| Implement from Figma. | [`figma-implement-design`](scripts/skills.sh) | Codex skill installed from a pinned upstream ref. |
| See Claude session state. | [`claude-hud@claude-hud`](configs/claude-settings.json) | Shows a local Claude status HUD. |
| Review security basics. | [`security-guidance`](configs/claude-settings.json) | Adds official security guidance. |
| Capture session history for llmwiki. | [`claude-mem`](configs/claude-settings.json) | Supplies the Claude/Codex session rows that llmwiki imports into its event log and vault. |
| Review Korean technical edits. | [`translation-mcp`](configs/codex/config.toml) + `korean-tech-humanizer` | Uses the MCP policy/review flow with local meaning-preserving editing and fidelity checks. |

`scripts/claude.sh` installs and updates `ui-clone-skills@voidmatcha`, but the
plugin stays disabled globally so its hooks and tool surface do not enter
unrelated sessions. A repository that needs the workflow opts in with
`"ui-clone-skills@voidmatcha": true` under `enabledPlugins` in its gitignored
`.claude/settings.local.json`.

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
| Rewrite general non-technical Korean prose. | [`humanize-korean`](plugins/local-skills/skills/humanize-korean/SKILL.md) | Handles the narrow general-prose path. Translation and technical editing use `translation-mcp` with `korean-tech-humanizer` instead. |
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
| [Claude Code] MCP | [`configs/mcp.json`](configs/mcp.json) | Registers local and hosted MCPs, including profile-routed Figma and the official pinned Zeplin server. Hooks and deny rules catch common mistakes. |
| [Codex] MCP | [`configs/codex/config.toml`](configs/codex/config.toml) | Registers [serena], [codegraph], [context7], [OpenAI Docs MCP], personal/default [Figma hosted MCP][Figma MCP], and disabled Zeplin/Atlassian profiles. |
| [Claude Code] Atlassian profiles | [`configs/atlassian-mcp/`](configs/atlassian-mcp/) | Project-scope, one-server templates. Load only `personal-ro.json`, `work-ro.json`, or `work-rw.json` for the active project. |
| Company/local fallback | `company/` overlay when present | Uses company-scoped MCP or local browser surfaces when hosted tools are inappropriate. |

Claude setup also removes the repository's explicit retired user-scope MCP
allowlist, currently `chrome-devtools`, so rerunning setup converges older
machines. It does not prune unknown or independently managed MCP registrations.

Credentials stay outside Git and should not be copied into every client config.
`dotfiles-auth` centralizes browser login, macOS Keychain storage, safe status
checks, repository routing, and process-scoped injection:

```bash
dotfiles-auth status
dotfiles-auth catalog                # names, routes, bindings, and stores; no values
dotfiles-auth setup all               # all OAuth flows + token-management pages
dotfiles-auth setup personal          # gh, Codex, Figma, Atlassian browser login
dotfiles-auth setup social            # LinkedIn, X/Twitter, Reddit browser sessions
dotfiles-auth set all                 # personal + work-read credentials
dotfiles-auth register sentry SENTRY_AUTH_TOKEN work-ro
dotfiles-auth set sentry              # Keychain owns the hidden one-time prompt
dotfiles-auth profile set work-ro     # writes only to this repo's .git/config
dotfiles-auth run work-ro -- sentry-cli info
dotfiles-auth run work-rw -- codex    # RW credentials remain command-scoped
```

Zsh completion covers commands, setup scopes, profiles, and registered
environment-token names. Restart the terminal or run `source ~/.zshrc` after
installation, then use `dotfiles-auth <TAB>`; completion reads only the safe
`catalog` metadata and never retrieves Keychain values.

`setup all`, `setup personal`, and `setup work` open the official Figma,
Zeplin, and Atlassian token-management pages after the supported OAuth flows.
Confirm the active browser account before generating a personal or work token;
the command opens an allowlisted page but never reads browser storage or copies
cookies. A failed browser launch is reported without aborting the other login
flows.

The default is `personal-ro`. A repository can select `work-ro` through local
Git config; `work-rw` cannot be persisted. Claude and Codex shell wrappers call
`dotfiles-auth run auto`, so Keychain values reach only the selected child
process. Figma and Zeplin use separate personal/work Keychain entries; the
selected profile exposes only the conventional `FIGMA_API_KEY` and
`ZEPLIN_ACCESS_TOKEN` names expected by their MCP servers. Git HTTPS continues
to use `git-credential-osxkeychain`, `gh auth
login` uses the system credential store, and SSH passphrases use the same
Keychain through `UseKeychain`.

`dotfiles-auth catalog` is the discovery contract for both people and agents.
It reports each credential's kind, profile route, environment binding, and
storage owner—including Git and browser-managed sessions—without retrieving a
secret value. Use it instead of searching Keychain, browser profiles, or shell
files for credentials.

`set personal`, `set work`, and `set all` batch the registered credentials;
`set all` intentionally excludes `work-rw`. Any environment-token consumer—CLI,
SDK, automation, or MCP—can use `register <name> <ENV_VAR> <profile>` without an
auth-script edit. Routing metadata lives at
`~/.config/dotfiles-auth/credentials.tsv`, while the value stays in Keychain.
`unregister <name>` removes both. The consuming program must still support the
declared environment variable; registration does not install or reconfigure it.

Browser sessions are a separate credential kind. The current [LinkedIn MCP
server] keeps its local browser profile under `~/.linkedin-mcp/`, [twitter-cli]
uses the signed-in browser directly by default, and [rdt-cli] owns its saved
Reddit session. `dotfiles-auth setup social` orchestrates those supported login
flows and `status` reports their local state, but it never copies raw cookies
into the shared environment. If a different client truly requires literal
token variables, register those variables individually and route them only to
the required profile.

Jira and Confluence share the selected Atlassian identity because both are
served by Atlassian Rovo MCP. Personal/work and read/write credentials remain
separate; their provider scopes, not the profile label, enforce permissions.

Atlassian API credentials, when OAuth is not sufficient for multiple identities
or a hard RO/RW split, use the matching Keychain entry and exactly one profile:

- Claude Code: copy or merge one file from `configs/atlassian-mcp/` into the
  project's `.mcp.json`. The allowlist permits all three names, but global
  settings enable none of them.
- Codex: keep the three global entries disabled and set `enabled = true` for
  only the matching server in project-local `.codex/config.toml`.

Use `personal-ro` for personal Jira/Confluence reads, `work-ro` for company
reads, and `work-rw` only for an explicitly requested mutation. The token scopes
remain the actual read/write boundary.

Do not route internal URLs through hosted tools such as [Exa], [Jina Reader], or personal/default [Figma hosted MCP][Figma MCP]. Company Figma context is separate. Use the company fallback (`figma-developer-mcp`) or a local browser surface.

[agent-browser] is a qualitative token-pressure control for targeted browser observation and authenticated browsing. It is not a numeric savings claim.

### Tool routing

| Task | Default tool | Reason |
| --- | --- | --- |
| Explain code flow, route handlers, or symbol traces. | [codegraph] | Pre-indexed graph for cross-file flow. |
| Rename, edit, or inspect references. | [serena] | LSP-backed symbol-aware edits and references. |
| Clean public web page extraction. | [Jina Reader] or [defuddle] | Fast Markdown extraction for public pages. Example: `defuddle parse <url> --markdown`. |
| Broad public web research. | [Exa] | Public search only, not for sensitive or internal URLs. |
| Authenticated or sensitive browsing. | [agent-browser] with an identity-specific persistent profile | Keeps auth and internal context out of hosted readers without exposing the daily Chrome profile. |
| Throwaway browser automation. | [agent-browser] | Clean browser automation for local targets; reap leftovers with [`agent-reap`](plugins/local-skills/skills/agent-reap/SKILL.md). |
| Session context policy. | [`context-check`](plugins/local-skills/skills/context-check/SKILL.md) | Returns continue, compact, clear, or handoff advice. |

Web tooling note: [defuddle] is installed with `npm install -g defuddle`.

Authenticated browser state uses separate local-only profiles. Choose the path
that matches the active identity; never combine personal and work sessions:

```bash
agent-browser --profile "$HOME/.local/share/agent-browser/profiles/personal" open <url>
agent-browser --profile "$HOME/.local/share/agent-browser/profiles/work" open <url>
```

These directories contain login state, stay outside Git, and should be used only
on the matching trust surface. Do not attach automation to the daily Chrome
profile or keep a browser debugging endpoint open. Persistent authenticated
profiles also do not provide agent-browser's domain-containment mode; use a
fresh unauthenticated session when strict network containment is required.

When `defuddle` or a direct request returns a bot wall, redirect loop, empty
body, or Cloudflare interstitial, use [agent-browser]. A dead deep link should
be rediscovered from the site's own index before it is recorded as removed.
Use `agent-browser get text <selector>` or `agent-browser eval <js>` to inspect
the page; close an existing daemon first when a different profile matters.

For a byte-exact Claude Bash result, redirect `rtk proxy <cmd>` output to a
temporary file and inspect that file directly; the proxy alone is not evidence
that a surrounding transcript preserved every byte. For an explicit
context-pressure diagnosis, run
`python3 plugins/local-skills/skills/context-check/scripts/context_check.py diagnose --cwd "$PWD"`.

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

### Commit message protocol

Non-trivial commits include the following trailer block. Trivial typo,
dependency-bump, and formatting-only commits skip it.

```text
<subject line — imperative, ≤72 chars>

<body wrapped at 80 columns>

Constraint: <external limits; omit when none>
Rejected: <alternatives considered and why they were rejected; omit when none>
Confidence: <high | medium | low>
Scope-risk: <plausible breakage outside this diff; "none" is valid>
Not-tested: <unverified environment, integration, or race; "none" is valid>
```

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
[Hermes Agent]: https://github.com/NousResearch/hermes-agent
[Homebrew]: https://brew.sh/
[Jina Reader]: https://jina.ai/reader/
[lefthook]: https://lefthook.dev/
[LinkedIn MCP server]: https://github.com/stickerdaniel/linkedin-mcp-server
[Maven]: https://maven.apache.org/
[nvm]: https://github.com/nvm-sh/nvm
[Node.js]: https://nodejs.org/
[OpenAI Docs MCP]: https://developers.openai.com/mcp
[OpenJDK]: https://openjdk.org/
[OpenSSH]: https://www.openssh.com/
[purplemux]: https://github.com/subicura/purplemux
[pyenv]: https://github.com/pyenv/pyenv
[Python]: https://www.python.org/
[rdt-cli]: https://github.com/jackwener/rdt-cli
[RTK]: https://www.rtk-ai.app/
[SDKMAN!]: https://sdkman.io/
[serena]: https://github.com/oraios/serena
[Tailscale]: https://tailscale.com/
[Tailscale Serve]: https://tailscale.com/kb/1242/tailscale-serve/
[Tailscale SSH]: https://tailscale.com/kb/1193/tailscale-ssh/
[Tokscale]: https://tokscale.ai/u/voidmatcha
[twitter-cli]: https://github.com/jackwener/twitter-cli
[uv]: https://docs.astral.sh/uv/
[Zsh]: https://www.zsh.org/
