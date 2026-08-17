# Dotfiles agent contract

Keep this file short: it is symlinked to `~/.agent/AGENTS.md` and imported by
Claude via `~/.claude/CLAUDE.md`, so it is always-loaded guidance. For detailed
tool-routing tables and exact one-liners, open this dotfiles repo's
`README.md` on demand instead of memorizing detailed routing here.

## Core operating rules

- If something is genuinely ambiguous, stop, state what is unclear, and ask.
- Do not touch code unrelated to the request; do not clean up what you did not break.
- Do not recommend tool installs that are not in this dotfiles setup.
- Public web research goes through the `agent-reach` skill; it carries the source-routing and no-bulk-scrape boundaries. Sensitive/internal URLs never transit hosted readers (Jina, Exa) — fetch locally with `defuddle` or `agent-browser`.
- On authenticated platforms (LinkedIn, X, Reddit) use your own session at human pace. Automated polling or bulk collection risks the account itself.
- Keep enabled MCPs lean per project: aim for <10 enabled servers and <80 total active tools. Disable per-project via `/mcp` rather than uninstalling globally.
- Do not create stray top-level `*.md` files (`NOTES.md`, `SUMMARY.md`, `FINDINGS.md`, etc.) without explicit approval. Named policy files (`README`, `CLAUDE`, `AGENTS`, `CONTRIBUTING`, `LICENSE`, `CHANGELOG`, `SKILL`, `SECURITY`) and files under `docs/`, `skills/`, `.claude/`, `agents/`, or `commands/` are allowed.
- Use `*.local.md` only for machine/private overrides documented by a tracked file; these overrides are gitignored and must not weaken tracked safety or verification rules.
- Verify external facts where the research happens, not where it is reported: a research subagent runs `verify-output` on acquisitions, shutdowns, funding, licences, retirements, and version/date claims before returning them, and labels the rest unverified. Subagent output is a draft, not a source.

## Default tool routing

- Code architecture / "how does X reach Y" / route-to-handler questions:
  use codegraph first.
- Symbol-level edit, rename, references, or LSP-accurate refactor: use serena.
- A few known lines from a known file: read the file directly.
- Current public web page content: prefer Jina Reader or defuddle; for sensitive
  pages use local browser tooling.
- **Blocked by a bot wall → escalate to `agent-browser`, do not give up.** When
  `defuddle`/`curl` return 403, a redirect loop, an empty body, or a Cloudflare
  interstitial, open it with `agent-browser`. Read via
  `agent-browser get text <selector>` (a selector is required) or
  `agent-browser eval <js>`; `--profile` is ignored while a daemon is already
  running, so `agent-browser close` first if the profile matters.
  **A dead deep link usually means the page was replaced, not removed** — re-find
  it from the site's own index before recording anything as gone.
- Mixed non-code project content (docs, PDFs, papers, images, knowledge graphs)
  or explicit `/graphify`: use the graphify skill. For pure code structure,
  prefer codegraph/serena first.
- Current session context/cache pressure: run `$context-check` or
  `python3 plugins/local-skills/skills/context-check/scripts/context_check.py diagnose --cwd "$PWD"`.
- Claude Bash output is compressed by RTK; use `rtk proxy <cmd>` when raw output
  is required.

## llmwiki

- Questions about past decisions, failed attempts, or prior work on a project:
  search the vault first —
  `cd ~/dotfiles && python3 -m scripts.llmwiki search "<query>"`.
  Deep cross-session search stays with `mem-search`.
- The vault's hand-written sections (`## 실패한 시도`, `## 결정과 근거`) are
  human-owned. Do not write them unprompted; curation goes through the
  `llmwiki-curate` skill.
- `projects/` is compiled from sessions — never hand-write there. Notes go to
  `concepts/` (reusable judgement), `records/` (facts and tracking), `tasks/`
  (`llmwiki new --project`), or `library/` (imported source). Build artifacts
  stay outside the vault.
- Copy frontmatter keys from a neighbouring file before writing, then run
  `cd ~/dotfiles && python3 -m scripts.llmwiki lint`. A note is not done until
  lint is clean.
- Design and spec documents go to the vault's `library/` with `type: library`
  frontmatter. This overrides any skill's default spec path. `voidmatcha/dotfiles`
  is a public repo — plans, finances, and career material never land there.

## Commit message protocol

For any non-trivial commit (more than a one-line fix), include the trailer block
below. The trailers turn `git log` into a free decision log — future spelunkers
can `git log --grep='Rejected:'` to see what was *not* taken.

```text
<subject line — imperative, ≤72 chars>

<body wrap at 80>

Constraint: <external limits — API shapes, compliance, framework guarantees. Omit if there were none.>
Rejected: <alternatives you considered but discarded + one-line reason. Omit if no real alternatives existed.>
Confidence: <high | medium | low>
Scope-risk: <code outside this diff that could plausibly break. "none" is a valid answer.>
Not-tested: <things you couldn't verify (env, integration, race). "none" is valid.>
```

Trivial diffs (typo fix, dependency bump, formatting-only change) skip the
trailer block. Use judgment — if the commit touched logic, write the trailers.
