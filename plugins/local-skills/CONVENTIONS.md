# Local skills conventions

## Local-only overrides

Use `*.local.md` for machine-, company-, or project-private instructions that
must not be committed. The repo ignores these files by default.

Allowed locations:

- `plugins/local-skills/CONVENTIONS.local.md` for plugin-wide local policy.
- `plugins/local-skills/skills/<skill>/<skill>.local.md` for one skill.
- `configs/agents/*.local.md`, `configs/commands/*.local.md`, or matching
  tool-owned local paths when a tool explicitly documents that extension point.

Rules:

1. A tracked file must explicitly opt in before reading a local override.
2. Local overrides may add constraints, private routing, examples, or vocabulary.
3. Local overrides must not weaken safety, privacy, provenance, or verification
   requirements from tracked files.
4. Never rely on a local override for behavior required in CI or on a fresh clone.
5. When a local override materially changes behavior, mention that it was applied
   without revealing private contents.

## Local skills — when to use which

Local skills auto-trigger from their `description`; you describe the situation,
not the name. This index is for the judgment-call ones that are easy to forget:

| Situation | Skill |
| --- | --- |
| AI output to fact-check before trusting or publishing | `verify-output` |
| Bug / regression / flaky failure — find the cause | `hypothesis-debugging` |
| About to commit to a costly, hard-to-reverse plan | `premortem` |
| Need public web/GitHub research beyond local files | `agent-reach` |
| Imported or adapted an external agent asset | `source-provenance` |
| CodeGraph or Serena config/index looks stale | `code-intel-doctor` |
| Decide whether overlapping agent surfaces should be pruned | `agent-usage-audit` |
| Mine repeated corrections from local session JSONL | `session-feedback-audit` |
| Review Korean technical terminology without general copy-editing | `korean-technical-terminology` |
| Verify this dotfiles repo before install | `dotfiles-verify` |
| Decide continue / compact / clear / hand off | `context-check` |
| Hand work to a fresh Claude/Codex/OMX session | `handover` |
