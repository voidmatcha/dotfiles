# Local skills conventions

## Ownership: local skills win

Skills under `plugins/local-skills/skills/` are owned by this repo. Upstream
skills pulled by `scripts/skills.sh` are pinned copies that can be re-fetched at
any time. When a name appears on both sides, the local skill wins and the
upstream install is skipped — enforced in `install_upstream_skill_from_url`, not
just documented here.

The asymmetry is deliberate. A local skill has its only original in this repo,
while an upstream skill is one `curl` away from the pinned SHA. Losing the local
one is unrecoverable; skipping the upstream one costs nothing.

Two related guarantees in the same function:

- A locally edited upstream skill is backed up to `SKILL.md.backup` before being
  replaced, and identical content is left untouched so mtimes stay stable.
- Replacing a symlink logs where it pointed first. The install path deletes
  symlinks to swap in a directory, so without that line the target is gone with
  no record.

## Cache propagation

Claude Code reads a cached copy of this plugin, not the working tree, and
invalidates it on `plugin.json`'s `version` alone. Editing a skill without
bumping the version leaves the edit invisible while every command reports
success — measured once at 27 days stale and two skills short. `skills.sh`
detects the divergence and bumps the patch version to force a refresh; commit
the bumped manifests along with the skill change.

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
| Humanize general (non-technical) Korean prose / strip AI-tell rhythm | `humanize-korean` |
| Explicit translation, localization, post-edit, or same-language rewrite | `translation-mcp` |
| Korean technical editing and fidelity checks inside that flow | `korean-tech-humanizer` (external repo `~/Documents/korean-tech-humanizer`) |
| Verify this dotfiles repo before install | `dotfiles-verify` |
| Decide continue / compact / clear / hand off | `context-check` |
| Hand work to a fresh Claude/Codex session | `handover` |
