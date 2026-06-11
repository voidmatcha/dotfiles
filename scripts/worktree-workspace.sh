#!/bin/bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  agent-worktrees [--repo PATH] [--print|--url|--open|--cmux]
  agent-worktrees-cmux [--repo PATH]
  agent-worktree-url [--repo PATH] [BRANCH]
  agent-worktree-link [--repo PATH] [BRANCH]
  agent-worktree-cmux [--repo PATH] [BRANCH]

Generate a VS Code/code-server multi-root .code-workspace from `git worktree`
metadata, print a code-server URL, or open that URL in cmux's browser split.

Environment:
  CODE_SERVER_BASE_URL  Base URL for browser links (default: http://127.0.0.1:8088)
  CODE_SERVER_PORT      Port used when CODE_SERVER_BASE_URL is unset (default: 8088)
  XDG_CACHE_HOME        Workspace cache root (default: ~/.cache)
USAGE
}

script_name="$(basename "$0")"
repo_arg=""
branch_arg=""
mode="workspace"
open_url=false
open_cmux=false
cmux_focus="true"
cmux_workspace=""
cmux_window=""

case "$script_name" in
  agent-worktrees)
    mode="workspace"
    ;;
  agent-worktrees-cmux)
    mode="workspace-url"
    open_cmux=true
    ;;
  agent-worktree-url)
    mode="folder-url"
    ;;
  agent-worktree-link)
    mode="folder-link"
    ;;
  agent-worktree-cmux)
    mode="folder-url"
    open_cmux=true
    ;;
esac

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      [ "$#" -ge 2 ] || { echo "--repo requires a path" >&2; exit 64; }
      repo_arg="$2"
      shift 2
      ;;
    --branch)
      [ "$#" -ge 2 ] || { echo "--branch requires a branch name" >&2; exit 64; }
      branch_arg="$2"
      shift 2
      ;;
    --print|--workspace)
      mode="workspace"
      open_url=false
      open_cmux=false
      shift
      ;;
    --url)
      mode="workspace-url"
      open_url=false
      open_cmux=false
      shift
      ;;
    --open)
      mode="workspace-url"
      open_url=true
      open_cmux=false
      shift
      ;;
    --cmux|--deck)
      mode="workspace-url"
      open_url=false
      open_cmux=true
      shift
      ;;
    --folder-url)
      mode="folder-url"
      open_url=false
      open_cmux=false
      shift
      ;;
    --link)
      mode="folder-link"
      open_url=false
      open_cmux=false
      shift
      ;;
    --cmux-folder|--deck-folder)
      mode="folder-url"
      open_url=false
      open_cmux=true
      shift
      ;;
    --cmux-focus)
      [ "$#" -ge 2 ] || { echo "--cmux-focus requires true or false" >&2; exit 64; }
      cmux_focus="$2"
      shift 2
      ;;
    --cmux-workspace)
      [ "$#" -ge 2 ] || { echo "--cmux-workspace requires a cmux workspace ref" >&2; exit 64; }
      cmux_workspace="$2"
      shift 2
      ;;
    --cmux-window)
      [ "$#" -ge 2 ] || { echo "--cmux-window requires a cmux window ref" >&2; exit 64; }
      cmux_window="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 64
      ;;
    *)
      if [ -z "$branch_arg" ]; then
        branch_arg="$1"
      else
        echo "Unexpected argument: $1" >&2
        usage >&2
        exit 64
      fi
      shift
      ;;
  esac
done

if [ "$#" -gt 0 ]; then
  if [ -z "$branch_arg" ]; then
    branch_arg="$1"
  else
    echo "Unexpected argument: $1" >&2
    exit 64
  fi
fi

repo_lookup="${repo_arg:-$PWD}"
if ! repo_root="$(git -C "$repo_lookup" rev-parse --show-toplevel 2>/dev/null)"; then
  echo "Not inside a git worktree: $repo_lookup" >&2
  exit 2
fi

base_url="${CODE_SERVER_BASE_URL:-http://127.0.0.1:${CODE_SERVER_PORT:-8088}}"
cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/agent-worktrees"
mkdir -p "$cache_root"

result="$({
  REPO_ROOT="$repo_root" \
  BRANCH_ARG="$branch_arg" \
  MODE="$mode" \
  BASE_URL="$base_url" \
  CACHE_ROOT="$cache_root" \
  python3 - <<'PY'
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

repo_root = os.environ["REPO_ROOT"]
branch_arg = os.environ.get("BRANCH_ARG", "")
mode = os.environ["MODE"]
base_url = os.environ["BASE_URL"].rstrip("/") + "/"
cache_root = Path(os.environ["CACHE_ROOT"])


def git(*args, check=True):
    return subprocess.run(
        ["git", "-C", repo_root, *args],
        text=True,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def parse_worktrees(raw):
    records = []
    cur = {}
    for line in raw.splitlines():
        if not line:
            if cur:
                records.append(cur)
                cur = {}
            continue
        key, _, value = line.partition(" ")
        if value:
            cur[key] = value
        else:
            cur[key] = True
    if cur:
        records.append(cur)
    return [r for r in records if "worktree" in r and "bare" not in r]


def branch_name(record):
    branch = record.get("branch", "")
    if branch.startswith("refs/heads/"):
        return branch.removeprefix("refs/heads/")
    if branch:
        return branch
    return "detached"


def safe_slug(value):
    value = value.strip() or "worktrees"
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return value.strip("-") or "worktrees"


raw = git("worktree", "list", "--porcelain").stdout
worktrees = parse_worktrees(raw)
if not worktrees:
    print("No git worktrees found", file=sys.stderr)
    sys.exit(3)

common_dir = git("rev-parse", "--git-common-dir").stdout.strip()
common_path = Path(common_dir)
if not common_path.is_absolute():
    common_path = (Path(repo_root) / common_path).resolve()
repo_name = common_path.parent.name if common_path.name == ".git" else Path(repo_root).name
workspace_path = cache_root / f"{safe_slug(repo_name)}.worktrees.code-workspace"

seen_names = set()
folders = []
for record in worktrees:
    path = record["worktree"]
    branch = branch_name(record)
    base = Path(path).name
    label = f"{base} [{branch}]" if branch != "detached" else f"{base} [detached]"
    name = label
    suffix = 2
    while name in seen_names:
        suffix += 1
        name = f"{label} #{suffix}"
    seen_names.add(name)
    folders.append({"name": name, "path": path})

workspace = {
    "folders": folders,
    "settings": {
        "git.openRepositoryInParentFolders": "always",
        "git.repositoryScanIgnoredFolders": [],
    },
}
workspace_path.write_text(json.dumps(workspace, indent=2) + "\n")


def url_for(kind, path):
    return base_url + "?" + urlencode({kind: path})


def current_branch_or_path():
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.returncode == 0:
        return branch.stdout.strip()
    return repo_root


def select_worktree(selector):
    selector = selector or current_branch_or_path()
    selector_ref = selector if selector.startswith("refs/heads/") else f"refs/heads/{selector}"
    selector_path = Path(selector).expanduser()
    for record in worktrees:
        path = Path(record["worktree"])
        branch = record.get("branch", "")
        short = branch.removeprefix("refs/heads/") if branch.startswith("refs/heads/") else branch
        if selector in {str(path), path.name, short, branch, selector_ref}:
            return record
        try:
            if selector_path.exists() and selector_path.resolve() == path.resolve():
                return record
        except OSError:
            pass
    print(f"No worktree found for branch/path: {selector}", file=sys.stderr)
    sys.exit(4)


if mode == "workspace":
    print(workspace_path)
elif mode == "workspace-url":
    print(url_for("workspace", str(workspace_path)))
elif mode == "folder-url":
    target = select_worktree(branch_arg)
    print(url_for("folder", target["worktree"]))
elif mode == "folder-link":
    target = select_worktree(branch_arg)
    branch = branch_name(target)
    url = url_for("folder", target["worktree"])
    label = branch if branch != "detached" else Path(target["worktree"]).name
    print(f"\033]8;;{url}\033\\\\{label}\033]8;;\033\\\\")
else:
    print(f"Unknown mode: {mode}", file=sys.stderr)
    sys.exit(64)
PY
})"

if $open_cmux; then
  if ! command -v cmux >/dev/null 2>&1; then
    echo "cmux not found; cannot open cmux browser split" >&2
    echo "$result" >&2
    exit 69
  fi
  cmux_args=(browser open-split "$result" --focus "$cmux_focus")
  if [ -n "$cmux_workspace" ]; then
    cmux_args+=(--workspace "$cmux_workspace")
  fi
  if [ -n "$cmux_window" ]; then
    cmux_args+=(--window "$cmux_window")
  fi
  cmux "${cmux_args[@]}"
fi

if $open_url; then
  if command -v open >/dev/null 2>&1; then
    open "$result"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$result" >/dev/null 2>&1 &
  else
    echo "No browser opener found; open manually:" >&2
    echo "$result" >&2
    exit 69
  fi
fi

printf '%s\n' "$result"
