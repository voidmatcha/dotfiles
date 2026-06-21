# Purplemux display guardrails

Read this only after `handover` has selected purplemux as the visible display backend. `handover` owns the task packet and ACK/READY handshake; purplemux only provides workspace/tab control.

The local CLI advertises these operations via `purplemux help`:

```bash
purplemux workspaces
purplemux tab list -w WS
purplemux tab create -w WS [-n NAME] [-t TYPE]
purplemux tab send -w WS TAB_ID CONTENT...
purplemux tab status -w WS TAB_ID
purplemux tab result -w WS TAB_ID
purplemux tab close -w WS TAB_ID
purplemux tab browser url -w WS TAB_ID
purplemux tab browser screenshot -w WS TAB_ID [-o FILE] [--full]
purplemux tab browser console -w WS TAB_ID [--since MS] [--level LEVEL]
purplemux tab browser network -w WS TAB_ID [--since MS] [--method M] [--url SUBSTR] [--status CODE] [--request ID]
purplemux tab browser eval -w WS TAB_ID EXPR
purplemux api-guide
```

`purplemux api-guide` states that HTTP API calls require:

```text
x-pmux-token: <PMUX_TOKEN>
```

## Environment preflight

Fail closed unless all of these are true:

```bash
command -v purplemux
[ -n "${PMUX_PORT:-}" ]
[ -n "${PMUX_TOKEN:-}" ]
purplemux workspaces
```

If `PMUX_PORT` or `PMUX_TOKEN` is missing, do not try to guess them from logs or process lists. Use artifact-only handover or a different backend.

## Workspace and tab preflight

1. Choose a workspace id from `purplemux workspaces` or an explicit user-provided workspace.
2. List tabs before creating anything:

   ```bash
   purplemux tab list -w "$WS"
   ```

3. Reuse a healthy terminal/Claude/Codex tab only when the user requested reuse. Otherwise create a fresh tab:

   ```bash
   purplemux tab create -w "$WS" -n "handover-<target>-<suffix>" -t terminal
   ```

4. Record the workspace id, tab id, tab name, and tab type in `.omx/artifacts/<run>/coordinator-status.md` or `state.jsonl`.

## Send smoke check

Before sending an agent prompt, prove that the tab executes input in the target repo:

```bash
MARKER=".omx/artifacts/purplemux-smoke-$(date -u +%Y%m%d-%H%M%S).txt"
purplemux tab send -w "$WS" "$TAB_ID" "cd '$PWD' && date -u > '$MARKER' && echo READY >> '$MARKER'
"
sleep 3
test -s "$MARKER" && cat "$MARKER"
purplemux tab result -w "$WS" "$TAB_ID"
```

If the marker is missing or `tab result` shows the input did not reach a usable prompt, do not send the handover prompt. Create a new tab or fall back to artifact-only.

## Launching Claude/Codex/OMX

Use `launch-commands.json` from `handover.py init` as the command source. Send the target's `send_text` plus a newline, then send the generated `target-prompts/<target>.txt` as the first instruction only after the CLI is visible and ready.

```bash
purplemux tab send -w "$WS" "$TAB_ID" "<send_text>
"
purplemux tab status -w "$WS" "$TAB_ID"
purplemux tab result -w "$WS" "$TAB_ID"
```

Do not background TTY-bound agent CLIs. Keep Claude/Codex/OMX running in the visible tab and use a separate coordinator artifact for polling state.

## Status, recovery, and close

- Poll with `purplemux tab status -w "$WS" "$TAB_ID"` and capture output with `purplemux tab result -w "$WS" "$TAB_ID"`.
- If the tab is stuck before receiving the handover prompt, close only that known tab id with `purplemux tab close -w "$WS" "$TAB_ID"` and create a fresh one.
- If `handover.py validate --run-dir <dir>` is incomplete, do not close the source tab.
- `handover.py close-current` currently knows cmux source ids. For purplemux source closure, close only when the source workspace id and tab id are explicitly known and recorded; otherwise leave the source open and report why.
- Never close all tabs in a workspace as a recovery shortcut.
