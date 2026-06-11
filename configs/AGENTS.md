# Dotfiles agent contract

Keep this file short: it is symlinked to `~/.agent/AGENTS.md` and imported by
Claude via `~/.claude/CLAUDE.md`, so it is always-loaded guidance. For detailed
tool-routing tables and exact one-liners, open this dotfiles repo's
`docs/agent-reference.md` on demand instead of memorizing them here.

## Core operating rules

- If something is genuinely ambiguous, stop, state what is unclear, and ask.
- Do not touch code unrelated to the request, and do not clean up what you did
  not break.
- Do not recommend tools or installs that are not in this dotfiles setup.
- Do not transit sensitive/internal URLs through hosted services such as Jina or
  Exa. Use local alternatives such as `agent-browser` for sensitive browsing.
- Do not bulk-scrape platforms; X, Reddit, LinkedIn, Jina, and Exa have account
  flag or rate-limit risk.
- Keep enabled MCPs lean per project: aim for <10 enabled servers and <80 total
  active tools. Disable per-project via `/mcp` rather than uninstalling globally.
- Do not create stray top-level `*.md` files (`NOTES.md`, `SUMMARY.md`,
  `FINDINGS.md`, etc.) without explicit approval. Named policy files (`README`,
  `CLAUDE`, `AGENTS`, `CONTRIBUTING`, `LICENSE`, `CHANGELOG`, `SKILL`,
  `SECURITY`) and files under `docs/`, `skills/`, `.claude/`, `agents/`, or
  `commands/` are allowed.

## Default tool routing

- Code architecture / "how does X reach Y" / route-to-handler questions:
  use codegraph first.
- Symbol-level edit, rename, references, or LSP-accurate refactor: use serena.
- A few known lines from a known file: read the file directly.
- Current public web page content: prefer Jina Reader or defuddle; for sensitive
  pages use local browser tooling.
- Mixed non-code project content (docs, PDFs, papers, images, knowledge graphs)
  or explicit `/graphify`: use the graphify skill. For pure code structure,
  prefer codegraph/serena first.
- Current session context/cache pressure: run `$context-check` or
  `python3 plugins/local-skills/skills/context-check/scripts/context_check.py diagnose --cwd "$PWD"`.
- Claude Bash output is compressed by RTK; use `rtk proxy <cmd>` when raw output
  is required.
- Long Claude/Codex/OMX sessions default through Headroom wrappers when
  installed; bypass with `HEADROOM_DEFAULT=0`, a per-tool env override, or
  `command claude|codex|omx`.

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
