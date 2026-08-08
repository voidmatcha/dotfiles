---
name: worktree-open
description: "Build a browser VS Code (code-server) link for a git worktree or all worktrees of a repo. Use when the user asks to view, review, or open worktree source code in browser VS Code. Do not use to serve reports or build artifacts, and do not start a new preview server."
---

# Worktree open (code-server)

Use the bundled helper instead of retyping URL logic:

```bash
SKILL_DIR="/absolute/path/to/worktree-open"
python3 "$SKILL_DIR/scripts/worktree_open.py" [path]
python3 "$SKILL_DIR/scripts/worktree_open.py" --all [repo-or-worktree]
```

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md` (use the
path supplied by the skill loader). The bundled helper then works from any cwd.

## Address policy

The helper discovers the code-server base URL in this order:

1. `CODE_SERVER_BASE_URL` explicit override.
2. `CODE_SERVER_TAILSCALE_HOST` explicit tailnet host.
3. `tailscale serve status --json` mapping that proxies the configured local
   code-server bind address.
4. `tailscale status --json` MagicDNS name with the default/override port.
5. `tailscale ip -4` IPv4 fallback.
6. Local bind fallback from `~/.config/code-server/config.yaml`, then
   `http://127.0.0.1:8088`.

Tailscale links use HTTPS on port `8443` by default. Override with
`CODE_SERVER_TAILSCALE_PORT` only if Tailscale Serve is configured differently.

## Deliverable policy

Deliver a link by default; do not perform an action. Do **not** auto-open with
`open`, `cmux browser open-split`, or similar unless the user explicitly asks to
open it.

## Link modes

- Single folder/worktree: `?folder=<percent-encoded-absolute-path>`.
- All git worktrees: writes a `.code-workspace` under
  `~/.cache/agent-worktrees/` (or `$XDG_CACHE_HOME/agent-worktrees/`) and emits
  `?workspace=<percent-encoded-workspace-path>`.

Never create workspace files or artifacts inside the repo.

## Examples

```bash
# Current folder
python3 "$SKILL_DIR/scripts/worktree_open.py" .

# Specific folder from any current working directory
python3 "$SKILL_DIR/scripts/worktree_open.py" ~/work/some-repo

# Multi-root dashboard for all worktrees in the repo
python3 "$SKILL_DIR/scripts/worktree_open.py" --all ~/work/some-repo
```

If the URL does not respond, code-server or Tailscale Serve may be down. Check:

```bash
launchctl list | grep -i code-server
tailscale serve status
```
