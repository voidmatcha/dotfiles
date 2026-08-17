#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  TMPDIR_TEST="$(mktemp -d)"
  export LC_ALL=C
  export LANG=C
  export LC_CTYPE=C
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

@test "unsafe asset improver is quarantined outside the published skill root" {
  [ ! -e "$REPO_ROOT/plugins/local-skills/skills/asset-improver/SKILL.md" ]
  [ -f "$REPO_ROOT/plugins/local-skills/quarantine/asset-improver/SKILL.md" ]
}

@test "bundled executable skills document cwd-independent script resolution" {
  for skill in context-check handover session-feedback-audit worktree-open; do
    file="$REPO_ROOT/plugins/local-skills/skills/$skill/SKILL.md"
    grep -q 'SKILL_DIR=' "$file"
    ! grep -Eq 'python3 (plugins/local-skills|scripts/)' "$file"
  done
}

@test "bundled helpers execute from outside the dotfiles checkout" {
  cd "$TMPDIR_TEST"
  for script in \
    "$REPO_ROOT/plugins/local-skills/skills/context-check/scripts/context_check.py" \
    "$REPO_ROOT/plugins/local-skills/skills/handover/scripts/handover.py" \
    "$REPO_ROOT/plugins/local-skills/skills/session-feedback-audit/scripts/analyze_session_feedback_jsonl.py" \
    "$REPO_ROOT/plugins/local-skills/skills/worktree-open/scripts/worktree_open.py"; do
    run python3 "$script" --help
    [ "$status" -eq 0 ]
  done
}

@test "dotfiles-backed skills use an explicit repo root instead of caller cwd" {
  for skill in agent-reap agent-usage-audit code-intel-doctor dotfiles-verify source-provenance work-scope-guard; do
    file="$REPO_ROOT/plugins/local-skills/skills/$skill/SKILL.md"
    grep -q 'DOTFILES_DIR=' "$file"
    ! grep -Eq '`?python3 scripts/|`?bash scripts/' "$file"
  done
}

@test "Korean prose is limited to intentional bilingual or Korean-specific surfaces" {
  python3 - "$REPO_ROOT/plugins/local-skills" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
hangul = re.compile(r"[\u3131-\u318e\uac00-\ud7a3]")
# humanize-korean is the skill that polishes AI-written Korean. Its body being
# Korean is itself the "Korean-specific surface" this test allows.
# llmwiki-curate edits a Korean vault. Its section headings ("## 실패한 시도
# (다시 하지 말 것)") and CLI output are Korean, so the instructions have to
# quote those strings verbatim.
# job-watch uses the same vault. The design-note wikilink
# ([[2026-08-15-채용-아카이빙-설계]]) and the view names ("관찰 중 / 지원 예정 /
# 지원함") are Korean, so they are quoted as-is.
allowed_trees = {"handover", "humanize-korean", "job-watch",
                 "korean-technical-terminology", "llmwiki-curate",
                 "session-feedback-audit"}

for path in sorted((root / "skills").rglob("*")):
    if not path.is_file() or path.parts[-2:-1] == ("__pycache__",):
        continue
    relative = path.relative_to(root / "skills")
    if relative.parts[0] in allowed_trees:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.name == "SKILL.md" and text.startswith("---\n"):
        _, _, text = text.split("---\n", 2)
    assert not hangul.search(text), f"unexpected Korean prose: {relative}"

for manifest in (root / ".claude-plugin/plugin.json", root / ".codex-plugin/plugin.json"):
    assert not hangul.search(manifest.read_text(encoding="utf-8")), manifest
PY
}

@test "every published skill directory has an entrypoint" {
  for skill_dir in "$REPO_ROOT"/plugins/local-skills/skills/*; do
    [ -d "$skill_dir" ] || continue
    [ -f "$skill_dir/SKILL.md" ]
  done
}

@test "published skills reject maintainer homes and destructive Git recovery" {
  run grep -RInE \
    '(/Users/[[:alnum:]_.-]+|/home/[[:alnum:]_.-]+)|git[[:space:]]+(reset[[:space:]]+--hard|clean[[:space:]]+-[^[:space:]]*f)' \
    "$REPO_ROOT/plugins/local-skills/skills"
  [ "$status" -eq 1 ]
  [ -z "$output" ]
}

@test "no plugin file carries a maintainer home path, quarantine included" {
  # The check above only covers the published tree. Quarantined means "not
  # shipped as a skill", not "not published" — this repository is public, so an
  # absolute path in a quarantined file leaks the maintainer's username just as
  # readily. One had been sitting there, and nothing caught it because the scan
  # stopped at skills/.
  #
  # Destructive git patterns are deliberately not checked here: a quarantined
  # tool holding a dangerous command is the reason it is quarantined, not a
  # defect to fix.
  run grep -RInE '/Users/[[:alnum:]_.-]+|/home/[[:alnum:]_.-]+' \
    "$REPO_ROOT/plugins/local-skills"
  [ "$status" -eq 1 ]
  [ -z "$output" ]
}

@test "agent-reach health checks do not invoke its mutating doctor command" {
  skill="$REPO_ROOT/plugins/local-skills/skills/agent-reach/SKILL.md"
  ! grep -Eq '(^|&&[[:space:]]*)agent-reach doctor([[:space:]]|$)' "$skill"
  grep -q 're-register' "$skill"
}
