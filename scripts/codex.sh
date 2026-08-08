#!/bin/bash
set -euo pipefail
TAG="codex"
# shellcheck source=scripts/lib/common.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

usage() {
  cat <<'USAGE'
Usage: scripts/codex.sh [--dry-run] [--non-interactive]

Installs/normalizes Codex CLI + oh-my-codex config and Codex skills.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      ;;
    --non-interactive)
      NON_INTERACTIVE=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      warn "unknown argument: $1"
      usage >&2
      exit 2
      ;;
  esac
  shift
done

info "Setting up Codex CLI + oh-my-codex (omx)..."

CODEX_CONFIG_DIR="${CODEX_HOME:-$HOME/.codex}"
CODEX_SHARED_CONFIG="$DOTFILES_DIR/configs/codex/config.toml"
CODEX_CMUX_SKILL_REPO="https://github.com/manaflow-ai/cmux.git"
CODEX_CMUX_SKILL_PATH="skills/cmux"

sanitize_codex_shared_config() {
  local config_file="$CODEX_SHARED_CONFIG"
  [ -f "$config_file" ] || return 0

  local tmp_file
  tmp_file=$(mktemp)
  awk '
    BEGIN {
      dynamic_notify = "notify = [\"env\", \"-u\", \"LC_ALL\", \"-u\", \"LC_CTYPE\", \"bash\", \"-lc\", \"exec node \\\"$(npm root -g)/oh-my-codex/dist/scripts/notify-hook.js\\\" \\\"$@\\\"\", \"omx-notify\"]"
    }
    /^notify = .*oh-my-codex.*notify-(hook|dispatcher)\.js/ {
      print dynamic_notify
      next
    }
    # Machine-local state sections — must never live in the shared template.
    # Keep in sync with extract_machine_local_codex_sections below.
    /^\[/ {
      drop = ($0 ~ /^\[projects\."/ || $0 ~ /^\[marketplaces\./ || $0 ~ /^\[plugins\./ || $0 ~ /^\[hooks\.state/)
    }
    !drop { print }
  ' "$config_file" > "$tmp_file"

  if cmp -s "$tmp_file" "$config_file"; then
    rm -f "$tmp_file"
  else
    mv "$tmp_file" "$config_file"
    info "Removed machine-local Codex entries from shared config"
  fi
}

# Codex CLI uses config.toml as a mutable state store on top of user config:
# `codex plugin add` records [plugins."name@marketplace"], marketplace
# registration writes [marketplaces.*], project trust writes [projects."..."],
# and the one-time hook-trust prompt records [hooks.state.*] hashes. Those
# sections are machine-local by definition and must survive template
# refreshes — a plain template copy silently uninstalls every CLI-added
# plugin (e.g. ui-clone-skills@local, registered by the upstream installer
# that claude.sh runs earlier in the same pipeline) and re-triggers every
# hook-trust prompt.
extract_machine_local_codex_sections() {
  local config_file="$1"
  [ -f "$config_file" ] || return 0

  awk '
    # Keep in sync with the drop patterns in sanitize_codex_shared_config.
    /^\[/ {
      keep = ($0 ~ /^\[projects\."/ || $0 ~ /^\[marketplaces\./ || $0 ~ /^\[plugins\./ || $0 ~ /^\[hooks\.state/)
    }
    keep { print }
  ' "$config_file"
}

install_codex_config() {
  local dst="$CODEX_CONFIG_DIR/config.toml"
  local backup_dst tmp_file preserved=""

  ensure_dir "$CODEX_CONFIG_DIR"

  if $DRY_RUN; then
    info "[dry-run] cp $CODEX_SHARED_CONFIG -> $dst (preserving machine-local sections)"
    return 0
  fi

  tmp_file=$(mktemp)
  cp "$CODEX_SHARED_CONFIG" "$tmp_file"

  if [ -L "$dst" ]; then
    rm "$dst"
  elif [ -e "$dst" ]; then
    preserved="$(extract_machine_local_codex_sections "$dst")"
    if [ -n "$preserved" ]; then
      printf '\n%s\n' "$preserved" >> "$tmp_file"
    fi
    if cmp -s "$tmp_file" "$dst"; then
      rm -f "$tmp_file"
      return 0
    fi
    if grep -q "portable template" "$dst"; then
      warn "Refreshing managed Codex config at $dst"
    else
      backup_dst="$(next_backup_path "$dst")"
      warn "Backing up $dst -> $backup_dst"
      mv "$dst" "$backup_dst"
    fi
  fi

  # cat instead of mv: keeps the destination inode and mode stable.
  cat "$tmp_file" > "$dst"
  rm -f "$tmp_file"
  if [ -n "$preserved" ]; then
    info "Installed Codex config: $dst (template + preserved machine-local sections)"
  else
    info "Copied: $CODEX_SHARED_CONFIG -> $dst"
  fi
}


# WORKAROUND(oh-my-codex@0.18.11, 소스 검증 2026-06-12):
# 업스트림 결함 — hooks/extensibility/dispatcher.js가 process.env를 통째 상속해
# 네이티브 훅이 OMX_TMUX_HUD_OWNER/OMX_TMUX_HUD_LEADER_PANE을 물려받아 HUD pane을
# 재생성할 수 있음 (team/tmux-session.js scrubTeamWorkerHudOwnershipEnv와 비대칭=누락).
# 이 함수는 등록된 훅 명령에 `env -u ...` 접두를 박아 누수를 차단한다.
# 한계: 스크립트 실행 시점의 훅만 수정 — OMX가 훅을 재등록하면 재실행 필요
#       (그 빈틈은 .zshrc의 __dotfiles_cleanup_orphan_hud_panes가 보험).
# 롤백 조건: 업스트림이 훅 dispatch 시 HUD env scrub을 넣으면 이 함수와 호출부,
#            .zshrc의 precmd 정리(같은 날짜 WORKAROUND 주석)를 함께 제거할 것.
# 업스트림 이슈: https://github.com/Yeachan-Heo/oh-my-codex/issues (TBD)
sanitize_codex_hooks_single_hud() {
  local hooks_file="$CODEX_CONFIG_DIR/hooks.json"

  [ -f "$hooks_file" ] || return 0

  if $DRY_RUN; then
    info "[dry-run] sanitize OMX native hook HUD owner env in $hooks_file"
    return 0
  fi

  python3 - "$hooks_file" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
prefix = "env -u OMX_TMUX_HUD_OWNER -u OMX_TMUX_HUD_LEADER_PANE "
leading_owner_env = re.compile(
    r"^(?:env\s+(?:(?:-u\s+OMX_TMUX_HUD_OWNER|-u\s+OMX_TMUX_HUD_LEADER_PANE)\s+)+)+"
)
changed = 0

for entries in data.get("hooks", {}).values():
    for entry in entries:
        for hook in entry.get("hooks", []):
            command = hook.get("command")
            if not isinstance(command, str) or "codex-native-hook.js" not in command:
                continue
            normalized = leading_owner_env.sub("", command)
            next_command = prefix + normalized
            if next_command != command:
                hook["command"] = next_command
                changed += 1

if changed:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(changed)
PY
}

# claude-mem 은 Claude Code 플러그인으로 설치되지만 Codex 훅은 스스로 등록하지
# 않는다. 그 결과 Codex 세션은 두 달 가까이 하나도 기록되지 않았고, 아무 도구도
# 실패를 알리지 않았다 — 손으로 병합해서 복구했는데, 손으로 한 복구는 다음
# 머신에서 그대로 사라진다. 그래서 여기서 소유한다.
#
# 훅 명령은 플러그인이 배포하는 hooks/codex-hooks.json 을 그대로 쓴다. 명령을
# 이 저장소에 복사하면 claude-mem 이 경로 해석 방식을 바꿀 때마다 조용히 낡는다.
ensure_claude_mem_codex_hooks() {
  local hooks_file="$CODEX_CONFIG_DIR/hooks.json"
  local cache_root="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache/thedotmack/claude-mem"

  # stdout 은 호출부가 카운트로 읽는다. 로그는 전부 stderr 로 보낸다.
  [ -d "$cache_root" ] || { info "claude-mem plugin not installed — skipping Codex hook merge" >&2; return 0; }

  if $DRY_RUN; then
    info "[dry-run] merge claude-mem Codex hooks into $hooks_file" >&2
    return 0
  fi

  python3 - "$cache_root" "$hooks_file" <<'PY'
import json, sys
from pathlib import Path

cache_root, hooks_path = Path(sys.argv[1]), Path(sys.argv[2])


def version_key(d):
    base = d.name.split("-")[0]
    parts = [int(x) if x.isdigit() else 0 for x in base.split(".")[:3]]
    parts += [0] * (3 - len(parts))
    return (*parts, "-" not in d.name)


versions = [d for d in cache_root.iterdir()
            if d.is_dir() and d.name[:1].isdigit() and not (d / ".orphaned_at").exists()]
if not versions:
    print("no-plugin-version")
    raise SystemExit(0)

template = max(versions, key=version_key) / "hooks" / "codex-hooks.json"
if not template.is_file():
    print("no-template")
    raise SystemExit(0)

try:
    wanted = json.loads(template.read_text()).get("hooks", {})
except ValueError:
    # 읽을 수 없는 템플릿은 원하는 집합을 모른다는 뜻이다. 이 상태로
    # 진행하면 아래 정리 단계가 claude-mem 훅을 전부 지운다.
    print("bad-template")
    raise SystemExit(0)

if not any(g.get("hooks") for entries in wanted.values() for g in entries):
    # 빈 템플릿도 마찬가지다. "원하는 것이 없다" 가 아니라 "무엇을 원하는지
    # 모른다" 이므로 아무것도 지우지 않는다. 이것을 원하는 집합으로 취급하면
    # Codex 기록이 조용히 멈춘다 - 이 저장소가 두 달을 잃은 방식이다.
    print("empty-template")
    raise SystemExit(0)

try:
    # 0바이트는 손상이 아니라 아직 아무것도 없는 상태다. 잘린 쓰기로 흔히
    # 생기고 안전하게 대체할 수 있는데, 거부하면 병합이 영원히 막힌다.
    raw_live = hooks_path.read_text().strip() if hooks_path.is_file() else ""
    live = json.loads(raw_live) if raw_live else {}
except ValueError:
    # 읽을 수 없는 hooks.json 을 덮어쓰면 다른 도구의 훅까지 날아간다.
    # 가만히 두고 소리를 낸다 - 지금까지는 traceback 이 stderr 로만 가고
    # stdout 이 비어 호출부가 "할 일 없음" 으로 읽었다.
    print("bad-hooks-file")
    raise SystemExit(0)
live.setdefault("hooks", {})

# 이 파일에는 OMX, orca, ui-clone 훅이 같은 이벤트에 공존한다. 그래서
# claude-mem 이 소유한 항목만 골라내야 하는데, 명령 문자열은 버전마다
# 바뀐다 - 실측으로 13.2.0 은 7개, 13.13.1 은 5개이고 겹치는 문자열이
# 하나도 없다. 추가만 하면 업그레이드할 때마다 옛 명령이 남아 같은
# 이벤트에서 두 번 발동하고, 아무것도 그것을 지우지 않는다.
#
# 소유 표식은 플러그인 캐시 경로다. 두 버전 템플릿 모두 전 명령이 이것을
# 담고 있고, 이 파일의 다른 도구 훅 중에는 하나도 없다.
MARKER = "thedotmack/claude-mem"

wanted_commands = {str(h.get("command", ""))
                   for entries in wanted.values()
                   for g in entries for h in g.get("hooks", [])}

removed = 0
for event, entries in list(live["hooks"].items()):
    kept_groups = []
    for group in entries:
        keep = []
        for hook in group.get("hooks", []):
            cmd = str(hook.get("command", ""))
            if MARKER in cmd and cmd not in wanted_commands:
                removed += 1
                continue
            keep.append(hook)
        if keep:
            kept_groups.append({**group, "hooks": keep})
    live["hooks"][event] = kept_groups

def commands(entries):
    return {str(h.get("command", ""))
            for g in entries for h in g.get("hooks", [])}


added = 0
for event, entries in wanted.items():
    have = commands(live["hooks"].get(event, []))
    for group in entries:
        fresh = [h for h in group.get("hooks", [])
                 if str(h.get("command", "")) not in have]
        if not fresh:
            continue
        live["hooks"].setdefault(event, []).append({**group, "hooks": fresh})
        added += len(fresh)

if added or removed:
    backup = hooks_path.with_suffix(f".json.pre-claude-mem-merge")
    if hooks_path.is_file() and not backup.exists():
        backup.write_text(hooks_path.read_text())
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(live, indent=2, ensure_ascii=False) + "\n")
print(added)
PY
}

# llmwiki 훅. Claude 쪽은 settings.json 이 저장소 심링크라 등록이 곧 커밋이지만
# ~/.codex/hooks.json 은 실파일이고 OMX 가 재작성한다. 그래서 여기서 매번 확인한다.
ensure_llmwiki_codex_hooks() {
  local hooks_file="$CODEX_CONFIG_DIR/hooks.json"
  local dir="$DOTFILES_DIR/configs/llmwiki"

  [ -f "$dir/hook-session-start.sh" ] || { info "llmwiki hooks not in this checkout — skipping" >&2; return 0; }

  if $DRY_RUN; then
    info "[dry-run] register llmwiki hooks in $hooks_file" >&2
    return 0
  fi

  python3 - "$hooks_file" "$dir" <<'PY'
import json, sys
from pathlib import Path

hooks_path, hook_dir = Path(sys.argv[1]), Path(sys.argv[2])
wanted = {
    "SessionStart": hook_dir / "hook-session-start.sh",
    "UserPromptSubmit": hook_dir / "hook-user-prompt.sh",
}

live = json.loads(hooks_path.read_text()) if hooks_path.is_file() else {}
live.setdefault("hooks", {})

added = 0
for event, script in wanted.items():
    present = any(str(script) in str(h.get("command", ""))
                  for g in live["hooks"].get(event, []) for h in g.get("hooks", []))
    if present:
        continue
    live["hooks"].setdefault(event, []).append(
        {"hooks": [{"type": "command", "command": f'sh "{script}"', "timeout": 10}]})
    added += 1

if added:
    backup = hooks_path.with_suffix(".json.pre-llmwiki")
    if hooks_path.is_file() and not backup.exists():
        backup.write_text(hooks_path.read_text())
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(live, indent=2, ensure_ascii=False) + "\n")
print(added)
PY
}

install_codex_cmux_skill() {
  local skills_dir="$CODEX_CONFIG_DIR/skills"
  local dest="$skills_dir/cmux"
  local tmp_dir

  if $DRY_RUN; then
    info "[dry-run] install Codex cmux skill from $CODEX_CMUX_SKILL_REPO:$CODEX_CMUX_SKILL_PATH -> $dest"
    return 0
  fi

  if ! command -v git &>/dev/null; then
    warn "git not found; skipping Codex cmux skill install"
    return 0
  fi

  ensure_dir "$skills_dir"
  tmp_dir="$(mktemp -d)"

  if ! git clone --quiet --depth 1 --filter=blob:none --sparse "$CODEX_CMUX_SKILL_REPO" "$tmp_dir"; then
    rm -rf "$tmp_dir"
    warn "Failed to clone cmux repo; skipping Codex cmux skill install"
    return 0
  fi

  if ! git -C "$tmp_dir" sparse-checkout set "$CODEX_CMUX_SKILL_PATH" >/dev/null 2>&1; then
    rm -rf "$tmp_dir"
    warn "Failed to check out $CODEX_CMUX_SKILL_PATH; skipping Codex cmux skill install"
    return 0
  fi

  if [ ! -f "$tmp_dir/$CODEX_CMUX_SKILL_PATH/SKILL.md" ]; then
    rm -rf "$tmp_dir"
    warn "cmux skill missing SKILL.md upstream; skipping Codex cmux skill install"
    return 0
  fi

  if [ -e "$dest" ]; then
    rm -rf "$dest"
  fi

  cp -R "$tmp_dir/$CODEX_CMUX_SKILL_PATH" "$dest"
  rm -rf "$tmp_dir"
  info "Installed Codex cmux skill -> $dest"
}

sanitize_omx_native_agent_providers() {
  local agents_dir="$CODEX_CONFIG_DIR/agents"
  local explore_toml="$agents_dir/explore.toml"

  if [ ! -f "$explore_toml" ]; then
    return 0
  fi

  if $DRY_RUN; then
    info "[dry-run] sanitize stale Headroom provider from $explore_toml"
    return 0
  fi

  if grep -q '^model_provider = "headroom"$' "$explore_toml"; then
    python3 - "$explore_toml" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
out = [line for line in lines if line.strip() != 'model_provider = "headroom"']
if out != lines:
    path.write_text("".join(out), encoding="utf-8")
PY
    info "Removed stale Headroom provider from $explore_toml"
  fi
}

if ! $DRY_RUN; then
  sanitize_codex_shared_config
fi
install_codex_config

if $DRY_RUN; then
  if command -v codex &>/dev/null; then
    info "[dry-run] codex --version"
    if $UPGRADE; then
      info "[dry-run] would: npm install -g @openai/codex@latest"
      if command -v omx &>/dev/null; then
        info "[dry-run] would: omx update --stable (upgrade OMX + refresh generated user assets)"
      else
        info "[dry-run] would: npm install -g oh-my-codex@latest"
        info "[dry-run] would: omx update --stable (refresh generated user assets)"
      fi
    fi
  else
    info "[dry-run] npm install -g @openai/codex oh-my-codex"
    $UPGRADE && info "[dry-run] would: omx update --stable after install (refresh generated user assets)"
  fi
  if command -v omx &>/dev/null; then
    info "[dry-run] omx --version"
  else
    info "[dry-run] omx not installed — would install with oh-my-codex"
  fi
  install_codex_cmux_skill
  ensure_claude_mem_codex_hooks >/dev/null
  ensure_llmwiki_codex_hooks >/dev/null
  sanitize_omx_native_agent_providers
  if [ -x "$DOTFILES_DIR/scripts/skills.sh" ]; then
    bash "$DOTFILES_DIR/scripts/skills.sh" codex
  fi
  info "[dry-run] codex login status"
  info "[dry-run] omx setup / omx doctor are manual first-install checks"
  info "Codex CLI + oh-my-codex setup done"
  exit 0
fi

# ── Install Codex CLI + omx ──
# `omx` is Yeachan-Heo/oh-my-codex — a multi-agent orchestration runtime on
# top of the official Codex CLI. README install path:
#   npm install -g @openai/codex oh-my-codex
# `omx doctor` then verifies install shape; `omx setup` provisions native
# agents and prompts (run interactively on first use).
codex_upgrade_failed=0
if command -v codex &>/dev/null; then
  CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
  info "Found codex ${CODEX_VERSION}"
  # Upgrade Codex itself with npm. OMX must use its supported update command
  # below because that also refreshes generated prompts/skills/native agents.
  if $UPGRADE; then
    if command -v npm &>/dev/null; then
      info "Upgrading Codex CLI (--upgrade)..."
      if ! npm install -g @openai/codex@latest; then
        warn "Codex CLI upgrade failed"
        codex_upgrade_failed=1
      fi
    else
      warn "npm not found; cannot upgrade Codex CLI"
      codex_upgrade_failed=1
    fi
  fi
  if command -v omx &>/dev/null; then
    OMX_VERSION=$(omx --version 2>/dev/null || echo "unknown")
    info "Found omx ${OMX_VERSION}"
  else
    warn "omx not installed — run 'npm install -g oh-my-codex' to add the orchestration layer"
  fi
elif $DRY_RUN; then
  info "[dry-run] npm install -g @openai/codex oh-my-codex"
else
  if ! command -v npm &>/dev/null; then
    warn "npm not found in PATH"
    warn "Run 'bash $DOTFILES_DIR/scripts/dev.sh' first, or install Codex with Homebrew: brew install --cask codex"
    exit 1
  fi

  if npm install -g @openai/codex oh-my-codex; then
    info "Codex CLI + omx installed"
  else
    warn "npm install -g @openai/codex oh-my-codex failed"
    exit 1
  fi
fi

if $UPGRADE; then
  if ! command -v omx &>/dev/null; then
    if command -v npm &>/dev/null; then
      info "Installing oh-my-codex before generated-asset refresh..."
      if ! npm install -g oh-my-codex@latest; then
        warn "oh-my-codex install failed"
        codex_upgrade_failed=1
      fi
      hash -r 2>/dev/null || true
    else
      warn "npm not found; cannot install oh-my-codex"
      codex_upgrade_failed=1
    fi
  fi

  if command -v omx &>/dev/null; then
    info "Refreshing OMX stable channel and generated user assets..."
    if with_timeout 600 omx update --stable </dev/null; then
      info "OMX stable update + generated asset refresh completed"
    else
      warn "omx update --stable failed; generated user assets may be stale"
      codex_upgrade_failed=1
    fi
  else
    warn "omx is unavailable after install; generated user assets were not refreshed"
    codex_upgrade_failed=1
  fi
fi

install_codex_cmux_skill

merged=$(ensure_claude_mem_codex_hooks || true)
llmwiki_added=$(ensure_llmwiki_codex_hooks || true)
[ "${llmwiki_added:-0}" = "0" ] || info "registered $llmwiki_added llmwiki hook(s) in Codex"
case "${merged:-0}" in
  0|"") : ;;
  no-plugin-version|no-template|empty-template|bad-template|bad-hooks-file)
    # 어느 쪽이든 원하는 훅 집합을 모른다. 그 상태에서 조용히 넘어가면
    # Codex 기록이 멈춘 것을 아무도 모른다.
    warn "claude-mem Codex hook template unusable ($merged) — Codex sessions will not be recorded"
    warn "  existing hooks were left untouched; check the plugin install" ;;
  *) info "merged $merged claude-mem hook(s) into Codex — Codex sessions are recorded again" ;;
esac
sanitize_omx_native_agent_providers
if [ -x "$DOTFILES_DIR/scripts/skills.sh" ]; then
  bash "$DOTFILES_DIR/scripts/skills.sh" codex
fi

# ── Codex auth check ──
if command -v codex &>/dev/null; then
  if codex login status >/dev/null 2>&1; then
    info "codex auth already configured"
  else
    echo ""
    warn "codex is not authenticated yet."
    echo ""
    echo "Run 'codex login' for ChatGPT sign-in, or pipe an API key with:"
    echo "  printenv OPENAI_API_KEY | codex login --with-api-key"
    echo "Use 'codex login --device-auth' for a headless device-code flow."
    echo ""

    if $DRY_RUN; then
      info "[dry-run] would run: codex login"
    elif $NON_INTERACTIVE; then
      warn "Non-interactive mode: skipped codex login. Run it manually before first use."
    else
      read -rp "Run 'codex login' now? (Y/n) " run_auth
      if [[ "$run_auth" =~ ^[Nn]$ ]]; then
        warn "Skipped. Run 'codex login' manually before first use."
      else
        codex login || warn "codex login exited non-zero — re-run manually if needed"
      fi
    fi
  fi
elif $DRY_RUN; then
  info "[dry-run] codex login status"
else
  warn "codex is still not available on PATH. Run 'codex login' after installing it."
fi

sanitize_codex_shared_config

# ── omx setup / doctor (manual — interactive on first run) ──
# `omx setup` provisions native agents/prompts/hooks; `omx doctor` reports
# install shape. Both are interactive in the upstream, so we surface them
# as REQUIRED MANUAL STEPS rather than running blind.
if command -v omx &>/dev/null && ! $DRY_RUN; then
  echo ""
  warn "═════════════════════════════════════════════════════════════════"
  warn "  omx (oh-my-codex) — REQUIRED MANUAL STEPS after first install"
  warn "═════════════════════════════════════════════════════════════════"
  warn "  1) Provision native agents/prompts/hooks:"
  warn "       omx setup"
  warn "       bash $DOTFILES_DIR/scripts/codex.sh  # normalize machine-local paths afterwards"
  warn "     (--upgrade runs \`omx update --stable\` automatically on later updates)"
  warn ""
  warn "  2) Verify install shape + runtime prerequisites:"
  warn "       omx doctor"
  warn ""
  warn "  3) Roundtrip smoke test (auth + profile + base-URL):"
  warn "       omx exec --skip-git-repo-check -C . \"Reply with exactly OMX-EXEC-OK\""
  warn ""
  warn "  4) Recommended launch:"
  warn "       omx --madmax --high          # default: direct, no OMX tmux/HUD pane"
  warn "       omx --tmux --madmax --high   # opt-in managed tmux/HUD surface"
  warn "  Set OMX_LAUNCH_POLICY=tmux|detached-tmux|auto to override the dotfiles direct default."
  echo ""
fi

if [ "$codex_upgrade_failed" -ne 0 ]; then
  warn "Codex/OMX upgrade completed with errors"
  exit 1
fi

info "Codex CLI + oh-my-codex setup done"
