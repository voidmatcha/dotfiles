---
name: local-preview-server
description: "Serve local files, HTML reports, static directories, dashboards, or build artifacts through verified private browser-accessible URLs. Use when asked to serve, preview, open, expose, share, or make local web output accessible, including 서버 켜줘, 접속 가능하게 해줘, 웹에서 볼 수 있게 해줘, or HTML 보여줘."
---
# Local Preview Server

Use this skill when a user asks to serve, preview, open, expose, share, or make a local file, HTML page, generated report, dashboard, static directory, build output, or lightweight web artifact accessible in a browser.

Use the bundled helper instead of ad-hoc `nohup python -m http.server &` commands:

```bash
scripts/local-preview-server.sh start --path ./report.html --port 8377
scripts/local-preview-server.sh start --path ./dist
scripts/local-preview-server.sh status --port 8377
scripts/local-preview-server.sh stop --port 8377
```

Resolve the script path relative to this `SKILL.md`; for installed copies, `scripts/local-preview-server.sh` is next to the skill.

## Default posture

- Private/local/tailnet preview only. Do **not** create public internet exposure by default.
- Only use ngrok, Cloudflare Tunnel, Tailscale Funnel, Vercel/Netlify, or other public publishing when the user explicitly asks for public access.
- The helper serves static content with `python3 -m http.server -b 0.0.0.0 -d "$DIR" "$PORT"` so localhost, LAN, and tailnet clients can connect when the host firewall allows it.
- Prefer the verified Tailscale/tailnet URL for user-facing sharing when available; otherwise report the verified localhost URL and any LAN URL status.

## Workflow

1. Resolve the target path.
   - File target: serve its parent directory and report the exact encoded file URL.
   - Directory target: serve the directory and report `/` (using `index.html` when present, otherwise Python's directory listing).
2. Start or restart the durable server.
   - Prefer tmux with deterministic session name `local-preview-PORT`.
   - Fall back to a managed background process with PID/state files only when tmux is unavailable.
   - Logs go to `/tmp/local-preview-PORT.log`.
3. Verify before reporting success.
   - Confirm the known session/PID exists.
   - Confirm the port accepts connections.
   - Curl the exact localhost URL.
   - Curl the exact tailnet/LAN URLs when detected; if those fail, report them as failed rather than claiming they work.
4. Report the parseable key/value output from the helper:
   - `STATUS`, `PREFERRED_URL`, `LOCAL_URL`, optional `LAN_URL`/`TAILNET_URL`
   - `ROOT`, `TARGET`, `PORT`, `SESSION`, `PROCESS_MODE`, `LOG`
   - `STOP_COMMAND`
   - verification fields such as `LOCAL_VERIFY`, `TAILNET_VERIFY`, `LISTENER_VERIFY`

## Safe lifecycle rules

- Restarting the same port stops only the matching `local-preview-PORT` tmux session or PID file.
- If the requested port is occupied by an unrelated process, the helper chooses the next free port and reports `REQUESTED_PORT` plus the actual `PORT`; it never broadly kills listeners.
- Stop with `scripts/local-preview-server.sh stop --port PORT`; this only targets the known session/PID for that port.
- Do not use `tailscale serve` as the static server. If an existing Tailscale Serve rule is known to be stale and conflicts with this preview, clear only that port deliberately with `--clear-tailscale-serve-conflict` or by running `tailscale serve --http=PORT off` after confirming it is safe.
