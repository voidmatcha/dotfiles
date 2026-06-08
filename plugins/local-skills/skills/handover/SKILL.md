---
name: handover
description: Hand off the current task to fresh cmux tabs/sessions running OMX, Claude, or Codex; supports explicit target tags like handover:omx, handover:claude, and handover:codex as well as natural-language target inference; create durable handoff artifacts, require a mutual ACK/CONFIRM/READY handshake, retry or recover failed transfers, and close the current cmux tab/session only after the receiver proves it can continue.
---

# Handover

Use this when the user wants the current work moved to a new agent session/tab, especially phrases like `handover:omx`, `handover:claude`, `handover:codex`, "handover", "handoff", "새 세션", "새 탭에서 이어서", "omx/claude로 넘겨", or "넘어가면 현재 탭 닫아".

## When to use this instead of compact/resume

- Use **compact** when staying in the same session and most prior context is still relevant; it is quick but lossy because history is replaced by a summary.
- Use **resume/fork/native Codex Handoff** when the same product already preserves the thread/worktree safely.
- Use **this handover skill** when crossing tools or tabs (`omx` -> `claude`, `codex` -> `omx`), freeing the current cmux surface, or needing proof that a new receiver actually picked up the task.
- Do **not** use this as a routine compact replacement inside the same tool/session; the launch + handshake overhead only pays off when a fresh context, cross-tool transfer, or source-tab closure is valuable.

Cache-aware rule:

- If the current tool still has a warm prompt cache and the same session can continue, prefer staying put or `/compact`; a new handover target usually starts with a cold cache.
- If a Claude/owl cache-expiry warning appears, treat handover as a **workflow transfer**, not as a cache fix. `/clear` is cheapest when old context can be dropped; `/compact` is better when old context must be retained and one cache rebuild is acceptable.
- Handover becomes cheaper only when the receiver needs a small artifact-backed brief instead of rebuilding a large stale transcript, or when the current tab/tool must be replaced anyway.

Efficient handover is not a raw transcript dump. Use a structured brief with pointers to durable artifacts: objective, completed work, remaining work, decisions, evidence, git state, risks, and a mutual handshake.

For source-backed rationale, read `references/handover-patterns.md` only when the user asks about compact/resume tradeoffs or handover design.

## Contract

A handover is complete only when all requested target sessions prove the transfer. Use the cheapest proof that is safe for the situation:

### Fast handshake (default)

Best for ordinary single- or multi-target tab handover where the source only needs proof before closing:

1. **OFFER**: source writes a repo-local package under `.omx/artifacts/handover-<UTC>-<random>/`.
2. **READY**: each target reads the package and writes `targets/<target>/ready.json` with the shared token, cwd, git snapshot, understanding summary, and next action.
3. **Close**: source validates every READY and closes its current cmux surface only after `validate` returns complete.

### Verified handshake (`--handshake verified`)

Use only when the receiver must wait until the source confirms its ACK before doing substantive work:

1. **OFFER**: source writes a repo-local package under `.omx/artifacts/handover-<UTC>-<random>/`.
2. **ACK**: each target writes `targets/<target>/ack.json` with the shared token, cwd, git snapshot, understanding summary, and next action.
3. **CONFIRM**: source validates every ACK and writes `source-confirmed.json`.
4. **READY**: each target sees source confirmation, writes `targets/<target>/ready.json`, then starts work.
5. **Close**: source closes its current cmux surface only after `validate` returns complete.

Never close the current tab/session before READY is validated for every target. Prefer `fast`; `verified` costs an extra source/target roundtrip and is usually overkill for routine handover.

## Workflow

1. Resolve targets:
   - Explicit tags win: `handover:omx`, `handover:claude`, `handover:codex`, or combined forms like `handover:omx,claude`.
   - Without tags, infer from natural language: "omx랑 claude", "클로드로 넘겨", "codex 새 탭".
   - If unspecified, default to `omx` and do not ask unless target choice is materially risky.
2. Capture the current state: objective, constraints, changed files, test evidence, unresolved risks, and the exact next action.
3. Create the handoff package:

   ```bash
   python3 plugins/local-skills/skills/handover/scripts/handover.py init \
     --target-from "<raw user handover request, if available>" \
     --handshake fast \
     --target omx --target claude \
     --task "<current objective and next action>" \
     --success "<what proves the receiver can continue>" \
     --completed "<what has already been done>" \
     --remaining "<the receiver's first concrete next step>" \
     --decision "<important decision + why>" \
     --artifact "<path to evidence, diff, plan, log, or test output>" \
     --risk "<known blocker or failure mode>" \
     --note "<important constraint or risk>" \
     --close-current
   ```

   If using `--target-from`, omit `--target` unless you need to add an explicit target programmatically. `--target` is still useful for deterministic coordinator scripts.

4. Launch a real cmux terminal for each target. Apply `cmux-handoff-runner` preflight/smoke checks when creating or reusing cmux surfaces.
   - Use the generated `.omx/artifacts/handover-<UTC>-<random>/launch-commands.json` so targets start with the user's usual launch shape.
   - Rename target tabs/surfaces using the generated title, e.g. `handover-omx-a1b2c3`, so multiple handovers in one folder do not get confused.
   - Defaults:
     - `omx`: `omx --direct --xhigh --madmax` (matches this dotfiles repo's `configs/.zshrc` wrapper)
     - `claude`: `claude` through an interactive zsh command so the local `claude()` wrapper can add the Serena system-prompt override
     - `codex`: `codex` using the installed Codex config/profile defaults
   - Override per run with exact command env vars: `HANDOVER_OMX_COMMAND`, `HANDOVER_CLAUDE_COMMAND`, `HANDOVER_CODEX_COMMAND`.
   - Or append args with: `HANDOVER_OMX_ARGS`, `HANDOVER_CLAUDE_ARGS`, `HANDOVER_CODEX_ARGS`.
   - Prefer a verified existing workspace/surface when available.
   - Otherwise create a new cmux workspace or surface with `cwd` set to the repo root.
   - Start the target CLI in the foreground (`omx`, `claude`, or `codex`). Do not background TTY-bound agent CLIs.
   - Paste/send the generated `target-prompts/<target>.txt` as the first instruction to that session.

5. From the source session, wait and repair until the handshake completes:

   ```bash
   python3 plugins/local-skills/skills/handover/scripts/handover.py wait \
     --run-dir .omx/artifacts/handover-<UTC>-<random> \
     --timeout 900 \
     --interval 5
   ```

6. If `wait` reports missing/invalid ACK or READY:
   - read the target screen/process state with cmux;
   - resend the target prompt if the agent never received it;
   - recreate unhealthy cmux surfaces (`runtime=0`, no TTY, no shell process);
   - preserve local changes and never kill unrelated sessions;
   - keep retrying until `validate` is complete or a non-recoverable authority issue exists.

7. Close the source tab only after validation passes:

   ```bash
   python3 plugins/local-skills/skills/handover/scripts/handover.py close-current \
     --run-dir .omx/artifacts/handover-<UTC>-<random> \
     --execute
   ```

   If the current surface cannot be identified (`CMUX_WORKSPACE_ID`/`CMUX_SURFACE_ID` missing), report the completed handover and leave the current session open.

## Target session instruction

Each target receives a generated prompt. The target must:

- read `handoff.json` and `handoff.md`;
- in `fast` mode: write READY with summary/next-action before doing substantive work;
- in `verified` mode: write ACK, wait for `source-confirmed.json`, then write READY;
- continue the task from the handoff package and keep writing progress artifacts if the work is long-running.

## Completion evidence

Report these exact items:

- run directory;
- targets launched;
- `handover.py validate --run-dir <dir>` result;
- whether current tab was closed or why it could not be closed;
- remaining risks, if any.
