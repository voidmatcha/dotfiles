# Dotfiles agent contract

This is always-loaded guidance shared by Claude and Codex. Keep only durable scope,
safety, and routing here; open this dotfiles repo's `README.md` for detailed commands.

## Scope and safety

- Ask only when ambiguity changes the result or the next action is destructive,
  irreversible, credential-gated, or external-production.
- Preserve unrelated work and do not clean up code outside the request.
- Recommend only tools installed by this dotfiles setup.
- Public research uses `agent-reach`. Keep sensitive or internal URLs out of
  hosted readers, and use authenticated social platforms at human pace.
- Keep <10 enabled MCP servers and <80 active tools per project.
  Disable unused servers per project instead of uninstalling global profiles.
- Do not create stray top-level Markdown files. Private `*.local.md` overrides
  require a tracked contract and cannot weaken safety or verification rules.
- Verify material external facts at the research source. Treat subagent output
  as a draft until its cited evidence has been checked.

## Model and effort routing

- Effort changes depth, not scope or authority. A higher setting never permits
  extra files, actions, or acceptance criteria.
- Default to medium for normal implementation. Use low for bounded lookup or
  mechanical work, high for ambiguity, risk, or review, and xhigh only when a
  long-running complex task cannot be handled reliably at high.
- Raise model capability only after adequate context and a complete attempt are
  still insufficient. Harness-specific heavy modes stay opt-in.

## Tool and content routing

- Use codegraph for cross-file code flow, serena for symbol-accurate edits, and
  direct file reads for a few known lines.
- Route public web research through `agent-reach`; it owns source selection and
  bot-wall escalation. Use `context-check` for session pressure.
- Translation and same-language rewrites use `translation-mcp`. Korean technical
  prose also uses `korean-tech-humanizer`; terminology-only decisions use
  `korean-technical-terminology`.

## Identity boundaries

- Locate credential ownership with `dotfiles-auth catalog`; never search secret
  files or print values.
- Route Figma, Zeplin, and Atlassian by cwd/account; never fall back from missing work credentials to personal ones.
- Use the matching Atlassian read-only profile unless the user explicitly
  requests a mutation.
- Resolve the target `cloudId`, Jira project, or Confluence space before writes.
  On auth failure, fail closed instead of trying another token or identity.
- Keep Atlassian profiles disabled globally and enable exactly one per project.

## llmwiki

- Search the vault first for past decisions and prior work. Curate human-owned
  sections only through `llmwiki-curate`; never hand-write compiled `projects/`.
- Put reusable notes in the documented vault areas and lint after writes. Plans,
  finances, and career material never go into this public dotfiles repository.

Before a non-trivial commit, open the README's commit-message section. Trivial
typo, dependency-bump, and formatting-only commits do not need its trailers.
