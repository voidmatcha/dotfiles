# Display adapter contract for handover

Read this before `handover` launches or controls a visible receiver tab. This is an internal adapter contract, not a new public skill: `handover` still owns the task package, ACK/READY markers, validation, and source-session closure rules. Display backends only provide a place to show and control a Claude/Codex/OMX session.

## Backend selection

Use the first backend with enough evidence:

1. **Explicit user request**: "use cmux", "purplemux로 열어", `handover:cmux`, or `handover:purplemux`.
2. **Current attached surface**: `CMUX_WORKSPACE_ID`/`CMUX_SURFACE_ID` for cmux, or `PMUX_PORT`/`PMUX_TOKEN` plus a chosen workspace/tab for purplemux.
3. **Available backend**: installed CLI and healthy preflight checks.
4. **Artifact-only fallback**: create the handover package and target prompts, report the run directory, and do not pretend a visible tab was launched.

If two backends look available and neither was requested, prefer the one attached to the current session. If neither is attached, prefer cmux only when its runtime preflight passes; otherwise use artifact-only and explain the missing evidence.

## Required adapter operations

Every visible backend must support these operations before `handover` uses it:

| Operation | Required evidence |
| --- | --- |
| Detect backend | CLI/env/API evidence, not only a stale config file. |
| List/create target | A workspace/tab/surface id that can be reused in later commands. |
| Send input | A smoke command writes a marker file in the repo before any agent prompt is sent. |
| Read status/output | A command/API response can show whether the target received input or is idle/stuck. |
| Close target/source | Only close known ids, only after `handover.py validate` is complete or the user explicitly asked to close a failed target. |
| Record evidence | Store ids, commands, marker path, and status/result snippets under `.omx/artifacts/<run>/`. |

## Backend references

- cmux: read `cmux-display.md` and run its runtime + smoke checks before `cmux send`.
- purplemux: read `purplemux-display.md` and run its env + workspace/tab + smoke checks before `purplemux tab send`.

Do not mix commands across backends. A cmux `surface:*` id is not a purplemux tab id; a purplemux tab id is not a cmux surface.

## Fail-closed rules

- Do not send an agent prompt to a target that has not passed its smoke marker check.
- Do not infer successful launch from "tab created" or "workspace exists" alone.
- Do not background TTY-bound agent CLIs; keep Claude/Codex/OMX foregrounded in the visible terminal.
- Do not kill or close unrelated tabs/surfaces while recovering.
- Do not claim source-tab closure for purplemux unless a concrete workspace id and tab id were closed and recorded.
- When evidence is missing, keep the handover package and target prompt as the recovery artifact.
