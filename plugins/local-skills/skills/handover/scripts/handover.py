#!/usr/bin/env python3
"""Durable handover handshake helper for cmux/OMX/Claude/Codex sessions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_OUT_ROOT = Path(".omx/artifacts")
TARGET_ALIASES = {
    "omx": "omx",
    "oh-my-codex": "omx",
    "oh my codex": "omx",
    "claude": "claude",
    "claude-code": "claude",
    "claude code": "claude",
    "클로드": "claude",
    "codex": "codex",
    "코덱스": "codex",
}
TARGET_TAG_RE = re.compile(r"\b(?:handover|handoff|hand-over)\s*:\s*([A-Za-z0-9_,+|/-]+)", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"handover-{stamp}-{secrets.token_hex(3)}"


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip().lower()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_target(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return TARGET_ALIASES.get(normalized, normalized)


def split_target_list(value: str) -> list[str]:
    return [normalize_target(part) for part in re.split(r"[,+|/]+", value) if part.strip()]


def infer_targets_from_text(text: str) -> tuple[list[str], bool]:
    """Return (targets, explicit) where explicit means handover:<target> syntax was used."""
    explicit: list[str] = []
    for match in TARGET_TAG_RE.finditer(text):
        explicit.extend(split_target_list(match.group(1)))
    if explicit:
        return unique(explicit), True

    lowered = text.lower()
    inferred: list[str] = []
    for alias, target in TARGET_ALIASES.items():
        if alias in lowered:
            inferred.append(target)
    return unique(inferred), False


def resolve_targets(cli_targets: list[str], target_from: str) -> tuple[list[str], str]:
    cli = [normalize_target(target) for target in cli_targets]
    inferred, explicit = infer_targets_from_text(target_from)
    if explicit:
        return unique(cli + inferred), "explicit-tag"
    if cli:
        return unique(cli), "cli-target"
    if inferred:
        return inferred, "text-inferred"
    return ["omx"], "default"


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def target_command_parts(target: str) -> list[str]:
    override = os.environ.get(f"HANDOVER_{target.upper()}_COMMAND", "").strip()
    if override:
        return [override]

    args_override = os.environ.get(f"HANDOVER_{target.upper()}_ARGS", "").strip()
    if target == "omx":
        # Matches configs/.zshrc's default omx() wrapper for interactive launches.
        parts = ["omx", "--direct", "--xhigh", "--madmax"]
    elif target == "claude":
        # Let the user's interactive shell wrapper add its usual Serena prompt override.
        parts = ["claude"]
    elif target == "codex":
        # Codex defaults come from ~/.codex/config.toml unless overridden.
        parts = ["codex"]
    else:
        parts = [target]
    if args_override:
        parts.extend(shlex.split(args_override))
    return parts


def target_title(run_id: str, target: str) -> str:
    suffix = run_id.rsplit("-", 1)[-1] if "-" in run_id else run_id
    return f"handover-{target}-{suffix}"


def launch_commands(targets: list[str], cwd: Path, run_id: str) -> dict[str, dict[str, str]]:
    commands: dict[str, dict[str, str]] = {}
    for target in targets:
        parts = target_command_parts(target)
        if len(parts) == 1 and " " in parts[0]:
            base = parts[0]
        else:
            base = shell_join(parts)
        send_text = f"cd {shlex.quote(str(cwd))} && {base}"
        # Use an interactive zsh wrapper for cmux --command/new workspace launches
        # so zsh functions like claude() still apply when needed.
        cmux_command = f"zsh -ic {shlex.quote(send_text)}"
        commands[target] = {
            "title": target_title(run_id, target),
            "command": base,
            "send_text": send_text,
            "cmux_command": cmux_command,
        }
    return commands


def run_quiet(args: list[str], cwd: Path | None = None) -> str:
    try:
        return subprocess.check_output(args, cwd=str(cwd) if cwd else None, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def git_snapshot(cwd: Path) -> dict[str, Any]:
    upstream = run_quiet(["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=cwd)
    ahead_behind = ""
    if upstream:
        ahead_behind = run_quiet(["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"], cwd=cwd)
    return {
        "branch": run_quiet(["git", "branch", "--show-current"], cwd=cwd),
        "head": run_quiet(["git", "rev-parse", "--short", "HEAD"], cwd=cwd),
        "upstream": upstream,
        "ahead_behind": ahead_behind,
        "status_short": run_quiet(["git", "status", "--short"], cwd=cwd),
        "diff_stat": run_quiet(["git", "diff", "--stat"], cwd=cwd),
    }


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def append_event(run_dir: Path, event: str, **fields: Any) -> None:
    payload = {"at": utc_now(), "event": event, **fields}
    path = run_dir / "state.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def source_identity(args: argparse.Namespace, cwd: Path) -> dict[str, Any]:
    return {
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "cwd": str(cwd),
        "session": args.current_session or os.environ.get("OMX_SESSION_ID") or os.environ.get("CODEX_SESSION_ID") or "",
        "cmux_workspace": args.source_workspace or os.environ.get("CMUX_WORKSPACE_ID") or "",
        "cmux_surface": args.source_surface or os.environ.get("CMUX_SURFACE_ID") or "",
        "cmux_tab": os.environ.get("CMUX_TAB_ID") or "",
    }


def load_handoff(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "handoff.json"
    if not path.exists():
        raise SystemExit(f"handoff.json not found: {path}")
    return read_json(path)


def target_names(handoff: dict[str, Any]) -> list[str]:
    return [item["name"] for item in handoff.get("targets", [])]


def target_dir(run_dir: Path, target: str) -> Path:
    return run_dir / "targets" / target


def handshake_mode(handoff: dict[str, Any]) -> str:
    return str(handoff.get("handshake", "verified"))


def target_prompt(script: Path, run_dir: Path, target: str, handoff: dict[str, Any]) -> str:
    run_dir_q = shlex.quote(str(run_dir))
    script_q = shlex.quote(str(script))
    target_q = shlex.quote(target)
    header = f"""# Handover receiver prompt: {target}

You are the receiving `{target}` agent for handover run `{handoff['run_id']}`.

1. Move to the source repo:

```bash
cd {shlex.quote(handoff['cwd'])}
```

2. Read these artifacts:

- `{run_dir}/handoff.json`
- `{run_dir}/handoff.md`
"""
    if handshake_mode(handoff) == "fast":
        return header + f"""
3. Write READY before doing substantive task work. Replace the summary/next-action strings with your real understanding:

```bash
python3 {script_q} ready --run-dir {run_dir_q} --target {target_q} \\
  --summary "I understand the objective, constraints, current repo state, and next step." \\
  --next-action "I will continue from the handoff package now."
```

4. Continue the task from the handoff package. Preserve the run directory as your evidence trail.
"""

    return header + f"""
Do not do substantive task work until the mutual handshake is complete.

3. Write ACK. Replace the summary/next-action strings with your real understanding:

```bash
python3 {script_q} ack --run-dir {run_dir_q} --target {target_q} \\
  --summary "I understand the objective, constraints, current repo state, and next step." \\
  --next-action "After source confirmation, I will continue from the handoff package."
```

4. Wait until the source validates all ACKs and writes `{run_dir}/source-confirmed.json`.

5. Write READY:

```bash
python3 {script_q} ready --run-dir {run_dir_q} --target {target_q}
```

6. Continue the task from the handoff package. Preserve the run directory as your evidence trail.
"""


def write_handoff_markdown(run_dir: Path, handoff: dict[str, Any]) -> None:
    criteria = "\n".join(f"- {item}" for item in handoff.get("success_criteria", [])) or "- Receiver can continue safely."
    completed = "\n".join(f"- {item}" for item in handoff.get("completed_steps", [])) or "- Not specified."
    remaining = "\n".join(f"- {item}" for item in handoff.get("remaining_steps", [])) or "- Continue from the task/next action."
    decisions = "\n".join(f"- {item}" for item in handoff.get("decisions", [])) or "- Not specified."
    artifacts = "\n".join(f"- {item}" for item in handoff.get("artifacts", [])) or "- See git status and repo files."
    risks = "\n".join(f"- {item}" for item in handoff.get("risks", [])) or "- None stated."
    notes = "\n".join(f"- {item}" for item in handoff.get("notes", [])) or "- No extra notes."
    targets = "\n".join(f"- {item['name']}" for item in handoff.get("targets", []))
    launch_lines = []
    for target, command in handoff.get("launch_commands", {}).items():
        launch_lines.append(f"- {target}: `{command.get('send_text', command.get('command', ''))}`")
    launch_section = "\n".join(launch_lines) or "- Not generated."
    git = handoff.get("git", {})
    status = git.get("status_short") or "(clean)"
    if handshake_mode(handoff) == "fast":
        handshake_line = "OFFER -> target READY -> source validate/close-current."
    else:
        handshake_line = "OFFER -> target ACK -> source CONFIRM -> target READY -> source close-current."
    text = f"""# Handover {handoff['run_id']}

Created: {handoff['created_at']}
Source cwd: `{handoff['cwd']}`

## Task

{handoff['task']}

## Success criteria

{criteria}

## Completed steps

{completed}

## Remaining / next steps

{remaining}

## Decisions and provenance

{decisions}

## Artifacts / evidence to inspect

{artifacts}

## Risks / failure modes

{risks}

## Notes / constraints

{notes}

## Targets

{targets}

## Launch commands

{launch_section}

## Git snapshot

- branch: `{git.get('branch', '')}`
- head: `{git.get('head', '')}`
- upstream: `{git.get('upstream', '')}`
- ahead/behind: `{git.get('ahead_behind', '')}`
- diff stat: `{git.get('diff_stat', '')}`

```text
{status}
```

## Required handshake

{handshake_line}
"""
    atomic_write_text(run_dir / "handoff.md", text)


def cmd_init(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).expanduser().resolve()
    targets, target_source = resolve_targets(args.target or [], args.target_from or "")
    run_id = args.run_id or default_run_id()
    run_dir = (Path(args.out_root) / run_id).resolve() if Path(args.out_root).is_absolute() else (cwd / args.out_root / run_id).resolve()
    if run_dir.exists() and not args.force:
        raise SystemExit(f"run directory already exists: {run_dir} (use --force to overwrite)")

    token = secrets.token_urlsafe(18)
    idempotency_key = hashlib.sha256(f"{run_id}|{cwd}|{','.join(targets)}".encode("utf-8")).hexdigest()[:24]
    handoff: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "trace_id": run_id,
        "idempotency_key": idempotency_key,
        "token": token,
        "handshake": args.handshake,
        "created_at": utc_now(),
        "cwd": str(cwd),
        "task": args.task,
        "success_criteria": args.success or [],
        "completed_steps": args.completed or [],
        "remaining_steps": args.remaining or [],
        "decisions": args.decision or [],
        "artifacts": args.artifact or [],
        "risks": args.risk or [],
        "notes": args.note or [],
        "close_current_requested": bool(args.close_current),
        "source": source_identity(args, cwd),
        "git": git_snapshot(cwd),
        "targets": [{"name": target, "status": "offered"} for target in targets],
        "target_source": target_source,
        "launch_commands": launch_commands(targets, cwd, run_id),
    }

    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "handoff.json", handoff)
    write_handoff_markdown(run_dir, handoff)

    script = Path(__file__).resolve()
    prompts_dir = run_dir / "target-prompts"
    launch = handoff["launch_commands"]
    write_json(run_dir / "launch-commands.json", launch)
    for target in targets:
        (target_dir(run_dir, target)).mkdir(parents=True, exist_ok=True)
        atomic_write_text(prompts_dir / f"{target}.txt", target_prompt(script, run_dir, target, handoff))

    append_event(run_dir, "offer_created", targets=targets, cwd=str(cwd))
    summary = {
        "run_dir": str(run_dir),
        "targets": targets,
        "handoff_json": str(run_dir / "handoff.json"),
        "handoff_md": str(run_dir / "handoff.md"),
        "launch_commands": str(run_dir / "launch-commands.json"),
        "target_prompts": {target: str(prompts_dir / f"{target}.txt") for target in targets},
        "next": f"Launch targets, send their target prompt, then run: python3 {script} wait --run-dir {shlex.quote(str(run_dir))}",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def valid_ack(handoff: dict[str, Any], run_dir: Path, target: str) -> tuple[bool, str, dict[str, Any] | None]:
    path = target_dir(run_dir, target) / "ack.json"
    if not path.exists():
        return False, f"missing ACK for {target}: {path}", None
    try:
        data = read_json(path)
    except Exception as exc:
        return False, f"invalid ACK JSON for {target}: {exc}", None
    required = ["schema_version", "run_id", "target", "token", "status", "acknowledged_at", "cwd", "summary", "next_action", "git"]
    missing = [field for field in required if field not in data]
    if missing:
        return False, f"ACK for {target} missing fields: {', '.join(missing)}", data
    if data.get("schema_version") != SCHEMA_VERSION:
        return False, f"ACK for {target} has schema_version={data.get('schema_version')}", data
    if data.get("run_id") != handoff.get("run_id"):
        return False, f"ACK for {target} has wrong run_id", data
    if data.get("target") != target:
        return False, f"ACK for {target} has wrong target", data
    if data.get("token") != handoff.get("token"):
        return False, f"ACK for {target} has wrong token", data
    if data.get("status") != "acknowledged":
        return False, f"ACK for {target} status is not acknowledged", data
    if not str(data.get("summary", "")).strip() or not str(data.get("next_action", "")).strip():
        return False, f"ACK for {target} lacks summary or next_action", data
    return True, "", data


def valid_confirm(handoff: dict[str, Any], run_dir: Path) -> tuple[bool, str, dict[str, Any] | None]:
    path = run_dir / "source-confirmed.json"
    if not path.exists():
        return False, f"missing source confirmation: {path}", None
    try:
        data = read_json(path)
    except Exception as exc:
        return False, f"invalid source confirmation JSON: {exc}", None
    if data.get("token") != handoff.get("token"):
        return False, "source confirmation has wrong token", data
    if data.get("run_id") != handoff.get("run_id"):
        return False, "source confirmation has wrong run_id", data
    confirmed = set(data.get("targets", []))
    expected = set(target_names(handoff))
    if confirmed != expected:
        return False, f"source confirmation targets mismatch: expected={sorted(expected)} got={sorted(confirmed)}", data
    return True, "", data


def valid_ready(handoff: dict[str, Any], run_dir: Path, target: str) -> tuple[bool, str, dict[str, Any] | None]:
    path = target_dir(run_dir, target) / "ready.json"
    if not path.exists():
        return False, f"missing READY for {target}: {path}", None
    try:
        data = read_json(path)
    except Exception as exc:
        return False, f"invalid READY JSON for {target}: {exc}", None
    required = ["schema_version", "run_id", "target", "token", "status", "ready_at"]
    if handshake_mode(handoff) == "verified":
        required.append("saw_source_confirmed_at")
    else:
        required.extend(["summary", "next_action", "cwd", "git"])
    missing = [field for field in required if field not in data]
    if missing:
        return False, f"READY for {target} missing fields: {', '.join(missing)}", data
    if data.get("token") != handoff.get("token"):
        return False, f"READY for {target} has wrong token", data
    if data.get("run_id") != handoff.get("run_id") or data.get("target") != target:
        return False, f"READY for {target} has wrong run_id or target", data
    if data.get("status") != "ready":
        return False, f"READY for {target} status is not ready", data
    if handshake_mode(handoff) == "fast" and (
        not str(data.get("summary", "")).strip() or not str(data.get("next_action", "")).strip()
    ):
        return False, f"READY for {target} lacks summary or next_action", data
    return True, "", data


def validation_report(run_dir: Path) -> dict[str, Any]:
    handoff = load_handoff(run_dir)
    mode = handshake_mode(handoff)
    errors: list[str] = []
    targets: dict[str, Any] = {}
    for target in target_names(handoff):
        ack_ok, ack_error, ack = valid_ack(handoff, run_dir, target)
        ready_ok, ready_error, ready = valid_ready(handoff, run_dir, target)
        if mode == "verified" and not ack_ok:
            errors.append(ack_error)
        if not ready_ok:
            errors.append(ready_error)
        targets[target] = {
            "ack": ack_ok,
            "ready": ready_ok,
            "ack_at": ack.get("acknowledged_at") if ack else "",
            "ready_at": ready.get("ready_at") if ready else "",
        }
    if mode == "verified":
        confirm_ok, confirm_error, confirm = valid_confirm(handoff, run_dir)
    else:
        confirm_ok, confirm_error, confirm = True, "", None
    if mode == "verified" and not confirm_ok:
        errors.append(confirm_error)
    return {
        "complete": not errors,
        "run_dir": str(run_dir),
        "run_id": handoff.get("run_id"),
        "handshake": mode,
        "targets": targets,
        "source_confirmation_required": mode == "verified",
        "source_confirmed": confirm_ok if mode == "verified" else False,
        "source_confirmed_at": confirm.get("confirmed_at") if confirm else "",
        "errors": errors,
    }


def cmd_ack(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    handoff = load_handoff(run_dir)
    target = args.target.strip().lower()
    if target not in target_names(handoff):
        raise SystemExit(f"target {target!r} not offered in handoff")
    cwd = Path(handoff["cwd"]).resolve()
    ack = {
        "schema_version": SCHEMA_VERSION,
        "run_id": handoff["run_id"],
        "target": target,
        "token": handoff["token"],
        "status": "acknowledged",
        "acknowledged_at": utc_now(),
        "summary": args.summary,
        "next_action": args.next_action,
        "cwd": str(cwd),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "cmux_workspace": args.workspace or os.environ.get("CMUX_WORKSPACE_ID") or "",
        "cmux_surface": args.surface or os.environ.get("CMUX_SURFACE_ID") or "",
        "git": git_snapshot(cwd),
    }
    write_json(target_dir(run_dir, target) / "ack.json", ack)
    append_event(run_dir, "target_ack", target=target)
    print(json.dumps({"ack": True, "target": target, "path": str(target_dir(run_dir, target) / "ack.json")}, ensure_ascii=False))
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    handoff = load_handoff(run_dir)
    errors: list[str] = []
    ack_payloads: dict[str, Any] = {}
    for target in target_names(handoff):
        ok, error, data = valid_ack(handoff, run_dir, target)
        if not ok:
            errors.append(error)
        elif data is not None:
            ack_payloads[target] = data
    if errors:
        print(json.dumps({"confirmed": False, "errors": errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        append_event(run_dir, "source_confirm_failed", errors=errors)
        return 1
    confirm = {
        "schema_version": SCHEMA_VERSION,
        "run_id": handoff["run_id"],
        "token": handoff["token"],
        "status": "confirmed",
        "confirmed_at": utc_now(),
        "confirmed_by": {
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "cmux_workspace": args.workspace or os.environ.get("CMUX_WORKSPACE_ID") or handoff.get("source", {}).get("cmux_workspace", ""),
            "cmux_surface": args.surface or os.environ.get("CMUX_SURFACE_ID") or handoff.get("source", {}).get("cmux_surface", ""),
        },
        "targets": target_names(handoff),
        "acknowledged_at": {target: ack_payloads[target].get("acknowledged_at", "") for target in target_names(handoff)},
    }
    write_json(run_dir / "source-confirmed.json", confirm)
    append_event(run_dir, "source_confirmed", targets=target_names(handoff))
    print(json.dumps({"confirmed": True, "path": str(run_dir / "source-confirmed.json")}, ensure_ascii=False))
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    handoff = load_handoff(run_dir)
    target = args.target.strip().lower()
    if target not in target_names(handoff):
        raise SystemExit(f"target {target!r} not offered in handoff")
    if handshake_mode(handoff) == "verified":
        confirm_ok, confirm_error, confirm = valid_confirm(handoff, run_dir)
        if not confirm_ok:
            raise SystemExit(confirm_error)
    else:
        confirm = {}
    cwd = Path(handoff["cwd"]).resolve()
    ready = {
        "schema_version": SCHEMA_VERSION,
        "run_id": handoff["run_id"],
        "target": target,
        "token": handoff["token"],
        "status": "ready",
        "ready_at": utc_now(),
        "saw_source_confirmed_at": confirm.get("confirmed_at", "") if confirm else "",
        "summary": args.summary,
        "next_action": args.next_action,
        "cwd": str(cwd),
        "git": git_snapshot(cwd),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "cmux_workspace": args.workspace or os.environ.get("CMUX_WORKSPACE_ID") or "",
        "cmux_surface": args.surface or os.environ.get("CMUX_SURFACE_ID") or "",
    }
    write_json(target_dir(run_dir, target) / "ready.json", ready)
    append_event(run_dir, "target_ready", target=target)
    print(json.dumps({"ready": True, "target": target, "path": str(target_dir(run_dir, target) / "ready.json")}, ensure_ascii=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    report = validation_report(run_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["complete"] or args.no_fail else 1


def all_acks_valid(run_dir: Path) -> bool:
    handoff = load_handoff(run_dir)
    return all(valid_ack(handoff, run_dir, target)[0] for target in target_names(handoff))


def cmd_wait(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    handoff = load_handoff(run_dir)
    deadline = time.monotonic() + args.timeout
    last_errors: list[str] = []
    append_event(run_dir, "wait_started", timeout=args.timeout, interval=args.interval)
    while True:
        report = validation_report(run_dir)
        if report["complete"]:
            append_event(run_dir, "wait_complete")
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        last_errors = report["errors"]
        if handshake_mode(handoff) == "verified" and all_acks_valid(run_dir):
            cmd_confirm(argparse.Namespace(run_dir=str(run_dir), workspace="", surface=""))
        if time.monotonic() >= deadline:
            append_event(run_dir, "wait_timeout", errors=last_errors)
            print(json.dumps({"complete": False, "run_dir": str(run_dir), "errors": last_errors}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        time.sleep(args.interval)


def cmd_close_current(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    report = validation_report(run_dir)
    if not report["complete"]:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    handoff = load_handoff(run_dir)
    workspace = args.workspace or os.environ.get("CMUX_WORKSPACE_ID") or handoff.get("source", {}).get("cmux_workspace", "")
    surface = args.surface or os.environ.get("CMUX_SURFACE_ID") or handoff.get("source", {}).get("cmux_surface", "")
    if not workspace or not surface:
        print("handover complete, but current cmux workspace/surface is unknown; leaving source session open", file=sys.stderr)
        return 3
    command = ["cmux", "close-surface", "--workspace", workspace, "--surface", surface]
    if not args.execute:
        print(" ".join(shlex.quote(part) for part in command))
        return 0
    append_event(run_dir, "source_close_requested", workspace=workspace, surface=surface)
    time.sleep(args.delay)
    try:
        subprocess.check_call(command)
    except FileNotFoundError:
        append_event(run_dir, "source_close_failed", workspace=workspace, surface=surface, reason="cmux_not_found")
        print("handover complete, but cmux is not installed/on PATH; leaving source session open", file=sys.stderr)
        return 3
    except subprocess.CalledProcessError as exc:
        append_event(
            run_dir,
            "source_close_failed",
            workspace=workspace,
            surface=surface,
            reason=f"cmux_close_surface_exit_{exc.returncode}",
        )
        print(
            "handover complete, but cmux close-surface failed "
            f"(exit {exc.returncode}); leaving source session open",
            file=sys.stderr,
        )
        return 3
    append_event(run_dir, "source_close_complete", workspace=workspace, surface=surface)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and validate a multi-session handover handshake.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a handoff package and target prompts")
    init.add_argument("--target", action="append", default=[], help="target session type/name; repeat for multiple targets")
    init.add_argument("--target-from", default="", help="raw user request to infer targets from; explicit handover:<target> tags win")
    init.add_argument("--handshake", choices=["fast", "verified"], default="fast", help="fast is one target READY roundtrip; verified uses ACK/CONFIRM/READY")
    init.add_argument("--task", required=True, help="current objective and next action for receivers")
    init.add_argument("--success", action="append", default=[], help="success criterion; repeatable")
    init.add_argument("--completed", action="append", default=[], help="completed step; repeatable")
    init.add_argument("--remaining", action="append", default=[], help="remaining/next step; repeatable")
    init.add_argument("--decision", action="append", default=[], help="decision/provenance note; repeatable")
    init.add_argument("--artifact", action="append", default=[], help="artifact or evidence path; repeatable")
    init.add_argument("--risk", action="append", default=[], help="risk or failure mode; repeatable")
    init.add_argument("--note", action="append", default=[], help="constraint/risk/context note; repeatable")
    init.add_argument("--cwd", default=os.getcwd(), help="source repository cwd")
    init.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="artifact root")
    init.add_argument("--run-id", default="", help="explicit run id")
    init.add_argument("--force", action="store_true", help="allow overwriting an existing run directory")
    init.add_argument("--close-current", action="store_true", help="record intent to close source surface after validation")
    init.add_argument("--current-session", default="", help="source agent session id")
    init.add_argument("--source-workspace", default="", help="source cmux workspace id/ref")
    init.add_argument("--source-surface", default="", help="source cmux surface id/ref")
    init.set_defaults(func=cmd_init)

    ack = sub.add_parser("ack", help="target writes an ACK marker")
    ack.add_argument("--run-dir", required=True)
    ack.add_argument("--target", required=True)
    ack.add_argument("--summary", required=True)
    ack.add_argument("--next-action", required=True)
    ack.add_argument("--workspace", default="")
    ack.add_argument("--surface", default="")
    ack.set_defaults(func=cmd_ack)

    confirm = sub.add_parser("confirm", help="source validates ACKs and writes source confirmation")
    confirm.add_argument("--run-dir", required=True)
    confirm.add_argument("--workspace", default="")
    confirm.add_argument("--surface", default="")
    confirm.set_defaults(func=cmd_confirm)

    ready = sub.add_parser("ready", help="target writes READY after source confirmation")
    ready.add_argument("--run-dir", required=True)
    ready.add_argument("--target", required=True)
    ready.add_argument("--summary", default="")
    ready.add_argument("--next-action", default="")
    ready.add_argument("--workspace", default="")
    ready.add_argument("--surface", default="")
    ready.set_defaults(func=cmd_ready)

    validate = sub.add_parser("validate", help="validate full handover completion")
    validate.add_argument("--run-dir", required=True)
    validate.add_argument("--no-fail", action="store_true", help="exit 0 even if incomplete")
    validate.set_defaults(func=cmd_validate)

    wait = sub.add_parser("wait", help="wait, confirm ACKs, and finish when every target is READY")
    wait.add_argument("--run-dir", required=True)
    wait.add_argument("--timeout", type=int, default=600)
    wait.add_argument("--interval", type=float, default=5.0)
    wait.set_defaults(func=cmd_wait)

    close = sub.add_parser("close-current", help="close the source cmux surface after validation")
    close.add_argument("--run-dir", required=True)
    close.add_argument("--workspace", default="")
    close.add_argument("--surface", default="")
    close.add_argument("--delay", type=float, default=2.0)
    close.add_argument("--execute", action="store_true", help="actually close; without this, print command only")
    close.set_defaults(func=cmd_close_current)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
