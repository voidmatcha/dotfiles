#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
}

@test "Claude and Codex default to medium effort without changing their models" {
  python3 - "$REPO_ROOT" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
claude = json.loads((root / "configs/claude-settings.json").read_text())
codex = tomllib.loads((root / "configs/codex/config.toml").read_text())

assert "model" not in claude
assert claude["effortLevel"] == "medium"
assert codex["model"] == "gpt-5.6-sol"
assert codex["model_reasoning_effort"] == "medium"
PY
}

@test "always-loaded agent instructions stay concise and scope-bound" {
  run python3 - "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
claude = (root / "configs/CLAUDE.md").read_text()
shared = (root / "configs/AGENTS.md").read_text()
codex = (root / "configs/codex/AGENTS.md").read_text()

assert claude.splitlines()[-1] == "@~/.agent/AGENTS.md"
assert len(claude.splitlines()) <= 8
assert "Fable is opt-in" in claude
assert "Ultra" not in claude
assert "mem-search" not in shared
assert "Effort changes depth, not scope or authority." in shared
assert len(shared.splitlines()) <= 60
assert "Fable" not in shared
assert "Ultra" not in shared
assert len(codex.splitlines()) <= 48
assert "Ultra is opt-in" in codex
assert "Fable" not in codex
assert "agent metadata" in codex
assert "style-reviewer" not in codex
assert "Bare skill names do not activate skills by themselves." not in codex
assert "zero known errors" not in codex
PY
  [ "$status" -eq 0 ]
}

@test "Claude keeps only the deliberate global plugin surface" {
  python3 - "$REPO_ROOT" <<'PY'
import json
import sys
from pathlib import Path

plugins = json.loads(
    (Path(sys.argv[1]) / "configs/claude-settings.json").read_text()
)["enabledPlugins"]

assert plugins == {
    "claude-hud@claude-hud": True,
    "claude-mem@thedotmack": True,
    "local-skills@dotfiles-local": True,
    "security-guidance@claude-plugins-official": True,
    "ui-clone-skills@voidmatcha": False,
}

settings = json.loads(
    (Path(sys.argv[1]) / "configs/claude-settings.json").read_text()
)
assert "alwaysThinkingEnabled" not in settings
PY
}

@test "RTK hook keeps search compression but bypasses zero-value read rewrites" {
  python3 - "$REPO_ROOT" <<'PY'
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
config = tomllib.loads((root / "configs/rtk-config.toml").read_text())
excluded = set(config["hooks"]["exclude_commands"])

assert {"cat", "head", "tail", "curl", "playwright"} <= excluded
assert {"grep", "rg"}.isdisjoint(excluded)

guide = (root / "configs/RTK.md").read_text()
assert "directional estimate" in guide
assert "rtk read -l aggressive" in guide
assert "cat/head/tail" in guide
PY
}

@test "Claude subagents use role-appropriate model and effort" {
  python3 - "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "configs/agents"
expected = {
    "critic.md": ("opus", "high"),
    "debugger.md": ("opus", "high"),
    "security-reviewer.md": ("opus", "high"),
    "test-engineer.md": ("sonnet", "medium"),
    "git-master.md": ("sonnet", "low"),
    "scout.md": ("haiku", "low"),
}

for name, (model, effort) in expected.items():
    header = (root / name).read_text().split("---", 2)[1]
    assert f"model: {model}\n" in header, name
    assert f"effort: {effort}\n" in header, name
PY
}

@test "tool installers do not append to always-loaded policy files" {
  dev="$REPO_ROOT/scripts/dev.sh"
  run grep -Fq 'graphify install --platform' "$dev"
  [ "$status" -ne 0 ]
  run grep -Fq 'pip install --user graphifyy' "$dev"
  [ "$status" -ne 0 ]
  grep -Fq 'rtk init --global --hook-only' "$dev"
  run grep -Fq 'rtk init --global;' "$dev"
  [ "$status" -ne 0 ]
  grep -Fq 'restore_ui_clone_plugin_policy' "$REPO_ROOT/scripts/claude.sh"
  grep -Fq 'UI_CLONE_SKIP_HOOK_PROBE=1' "$REPO_ROOT/scripts/claude.sh"
  grep -Fq 'cleanup_ui_clone_staging_venv' "$REPO_ROOT/scripts/claude.sh"
  # Match the removed source text literally.
  # shellcheck disable=SC2016
  run grep -Fq 'rm -rf "$claude_plugin_source/.venv"' "$REPO_ROOT/scripts/claude.sh"
  [ "$status" -ne 0 ]
}

@test "technical Korean routes through Translation MCP and its editing skill" {
  shared="$REPO_ROOT/configs/AGENTS.md"
  readme="$REPO_ROOT/README.md"

  grep -Fq 'translation-mcp' "$shared"
  grep -Fq 'korean-tech-humanizer' "$shared"
  grep -Fq 'translation-mcp' "$readme"
  grep -Fq 'korean-tech-humanizer' "$readme"
}

@test "local plugin refreshes its marketplace after an automatic version bump" {
  python3 - "$REPO_ROOT/scripts/skills.sh" <<'PY'
import sys
from pathlib import Path

script = Path(sys.argv[1]).read_text()
start = script.index("if bump_local_plugin_patch_version; then")
update = script.index('claude plugin update "$CLAUDE_PLUGIN_ID"', start)
refresh = script.index(
    'claude plugin marketplace update "$CLAUDE_MARKETPLACE_NAME"', start
)
assert start < refresh < update
PY
}
