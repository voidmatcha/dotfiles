---
name: local-preview-server
description: "Serve local files, HTML reports, static directories, dashboards, or build artifacts through verified private/tailnet browser URLs. Use when asked to serve, preview, open, expose, share, or make local web output accessible, including 서버 켜줘, 접속 가능하게 해줘, 웹에서 볼 수 있게 해줘, or HTML 보여줘."
---

# Local / Tailnet Preview Server

Use this skill to serve a local file, HTML page, generated report, dashboard,
static directory, build output, or lightweight web artifact through a verified
private URL.

## Security posture

- Default exposure is **localhost-only** (`127.0.0.1`).
- For outside-this-machine access, prefer **Tailscale Serve** with
  `--tailscale-serve`; this keeps the preview bound to localhost and lets
  Tailscale enforce tailnet identity/ACLs.
- Do **not** bind to `0.0.0.0` by default. Use `--lan` or `--bind 0.0.0.0`
  only when LAN exposure is explicitly intended and the host firewall/trust
  boundary is understood.
- Do **not** create public internet exposure by default. Only use ngrok,
  Cloudflare Tunnel, Tailscale Funnel, Vercel/Netlify, or other public
  publishing when the user explicitly requests public exposure.

## Commands

Resolve the helper relative to this `SKILL.md`; for installed copies,
`scripts/local-preview-server.sh` is next to the skill.

```bash
scripts/local-preview-server.sh start --path ./report.html --port 8377
scripts/local-preview-server.sh start --path ./dist --tailscale-serve
scripts/local-preview-server.sh start --path ./dist --lan   # explicit LAN bind
scripts/local-preview-server.sh status --port 8377
scripts/local-preview-server.sh stop --port 8377
```

## Workflow

1. Resolve the target path.
   - File target: serve the parent directory and report the encoded file URL.
   - Directory target: report `/` and rely on `index.html` if present.
2. Start or restart a durable server.
   - Prefer tmux session `local-preview-PORT`.
   - Fall back to background PID/state files only when tmux is unavailable.
   - Logs go to `/tmp/local-preview-PORT.log` by default.
3. Verify before reporting success.
   - Confirm the known session/PID exists.
   - Confirm the port accepts local connections.
   - Curl the exact localhost URL.
   - If `--tailscale-serve` is used, curl the exact tailnet URL and report
     failure rather than claiming it works.
4. Report the parseable key/value output from the helper:
   - `STATUS`, `PREFERRED_URL`, `LOCAL_URL`, optional `LAN_URL`/`TAILNET_URL`
   - `ROOT`, `TARGET`, `PORT`, `BIND_ADDR`, `SESSION`, `PROCESS_MODE`, `LOG`
   - `STOP_COMMAND`

## Operational notes

- Restarting a port stops only the matching `local-preview-PORT` tmux session
  or known PID/state file; it never broadly kills listeners.
- If the requested port is occupied by an unrelated process, the helper chooses
  the next free port and reports `REQUESTED_PORT` plus the actual `PORT`.
- `stop --port PORT` clears only the known helper state/PID/session for that
  port. If the preview created a Tailscale Serve rule, stop also removes that
  helper-owned rule.
- Use `--clear-tailscale-serve-conflict` only when a stale Tailscale Serve rule
  for that preview port is known to conflict.
