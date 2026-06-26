#!/usr/bin/env python3
"""Advisory context/cache policy for Claude, Codex, and OMX sessions.

The hook path is intentionally cheap and fail-open: it only reads the current
hook payload and a small local state file, then optionally emits Claude
`additionalContext`. Heavy commands (agentsview/ccusage) are manual-only via
`diagnose`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from urllib.request import urlopen

STATE_PATH = Path(os.environ.get("CONTEXT_CHECK_STATE", "~/.cache/context-check/state.json")).expanduser()
HOOK_WARNING_INTERVAL_SECONDS = 15 * 60
HOOK_WARNING_INTERVAL_TURNS = 5
IDLE_WARN_MINUTES = 45.0
IDLE_RED_MINUTES = 60.0
TURN_WARN = 45
TURN_RED = 90
PROMPT_WARN_CHARS = 8_000
PROMPT_RED_CHARS = 20_000
TRANSCRIPT_WARN_BYTES = 5 * 1024 * 1024
TRANSCRIPT_RED_BYTES = 15 * 1024 * 1024


@dataclass
class Signal:
    name: str
    status: str
    detail: str
    severity: str = "info"  # info|warn|red


@dataclass
class Recommendation:
    action: str
    confidence: str
    reason: str
    if_new_or_disposable: str = "clear"
    if_same_task: str = "continue"
    if_cross_tool_or_poisoned: str = "handover"


def _now() -> float:
    override = os.environ.get("CONTEXT_CHECK_NOW")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return time.time()


def _read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("sessions", {})
                return data
    except Exception:
        pass
    return {"version": 1, "sessions": {}}


def _write_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # Hooks must never fail a prompt because state could not be persisted.
        return


def _load_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _session_key(payload: dict[str, Any], cwd: str | None = None) -> str:
    for key in ("session_id", "transcript_path", "conversation_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return f"cwd:{cwd or payload.get('cwd') or os.getcwd()}"


def _extract_prompt(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message", "input"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _transcript_size(payload: dict[str, Any]) -> int | None:
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None
    try:
        return Path(path).expanduser().stat().st_size
    except OSError:
        return None


def _severity_rank(severity: str) -> int:
    return {"info": 0, "warn": 1, "red": 2}.get(severity, 0)


def _state_sessions_for_cwd(state: dict[str, Any], cwd: str) -> list[dict[str, Any]]:
    sessions = state.get("sessions", {})
    if not isinstance(sessions, dict):
        return []
    out: list[dict[str, Any]] = []
    for key, value in sessions.items():
        if not isinstance(value, dict):
            continue
        if value.get("cwd") == cwd or key == f"cwd:{cwd}":
            copied = dict(value)
            copied["key"] = key
            out.append(copied)
    out.sort(key=lambda item: float(item.get("last_prompt_at") or 0), reverse=True)
    return out


def _collect_local_signals(payload: dict[str, Any], state: dict[str, Any], cwd: str, now: float, update: bool) -> tuple[list[Signal], dict[str, Any]]:
    key = _session_key(payload, cwd)
    sessions = state.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        state["sessions"] = sessions = {}
    current = sessions.get(key) if isinstance(sessions.get(key), dict) else {}

    previous_prompt_at = current.get("last_prompt_at")
    idle_minutes = None
    if isinstance(previous_prompt_at, (int, float)) and previous_prompt_at > 0:
        idle_minutes = max(0.0, (now - float(previous_prompt_at)) / 60.0)

    turns = int(current.get("turns") or 0) + (1 if update else 0)
    prompt = _extract_prompt(payload)
    prompt_chars = len(prompt)
    transcript_bytes = _transcript_size(payload)

    signals: list[Signal] = []
    if idle_minutes is not None:
        severity = "red" if idle_minutes >= IDLE_RED_MINUTES else "warn" if idle_minutes >= IDLE_WARN_MINUTES else "info"
        signals.append(Signal("idle", "observed", f"last prompt was {idle_minutes:.1f}m ago", severity))
    else:
        signals.append(Signal("idle", "unknown", "no prior prompt timestamp for this session", "info"))

    turn_severity = "red" if turns >= TURN_RED else "warn" if turns >= TURN_WARN else "info"
    signals.append(Signal("turns", "observed", f"local hook turn count is {turns}", turn_severity))

    if prompt_chars:
        prompt_severity = "red" if prompt_chars >= PROMPT_RED_CHARS else "warn" if prompt_chars >= PROMPT_WARN_CHARS else "info"
        signals.append(Signal("prompt_size", "observed", f"current prompt is {prompt_chars:,} chars", prompt_severity))

    if transcript_bytes is not None:
        transcript_severity = "red" if transcript_bytes >= TRANSCRIPT_RED_BYTES else "warn" if transcript_bytes >= TRANSCRIPT_WARN_BYTES else "info"
        signals.append(Signal("transcript_size", "observed", f"transcript is {transcript_bytes / (1024 * 1024):.1f} MiB", transcript_severity))

    if update:
        current.update(
            {
                "cwd": cwd,
                "turns": turns,
                "last_prompt_at": now,
                "last_prompt_chars": prompt_chars,
                "last_transcript_bytes": transcript_bytes,
                "last_hook_event": payload.get("hook_event_name") or payload.get("event") or "UserPromptSubmit",
            }
        )
        sessions[key] = current

    return signals, current


def _run_command(cmd: list[str], timeout: int = 8) -> tuple[int | None, str, str]:
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return None, "", "not installed"
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {timeout}s"
    except Exception as exc:  # pragma: no cover - defensive fail-open
        return None, "", str(exc)


def _headroom_port_from_env() -> str:
    port = os.environ.get("HEADROOM_PORT")
    if port:
        return port
    for name in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        value = os.environ.get(name, "")
        match = re.search(r"127\.0\.0\.1:([0-9]+)|localhost:([0-9]+)", value)
        if match:
            return match.group(1) or match.group(2)
    return "8787"


def _headroom_proxy_ready(port: str) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/livez", timeout=0.6) as response:
            return 200 <= int(response.status) < 300
    except Exception:
        return False


def _collect_headroom_signal() -> Signal:
    active = os.environ.get("HEADROOM_AGENT_ACTIVE", "")
    mode = os.environ.get("HEADROOM_MODE", "cache")
    port = _headroom_port_from_env()
    ready = _headroom_proxy_ready(port)
    if active:
        status = "observed" if ready else "error"
        severity = "info" if ready else "warn"
        return Signal("headroom", status, f"active for {active}; mode={mode}; port={port}; proxy_ready={ready}", severity)
    if ready:
        return Signal("headroom", "observed", f"proxy ready on port {port}; mode={mode}", "info")
    if shutil.which("headroom"):
        return Signal("headroom", "available", "headroom installed but no active proxy detected", "info")
    return Signal("headroom", "unavailable", "headroom not installed or not on PATH", "info")


def _find_numeric_keys(obj: Any, interesting: tuple[str, ...], found: list[tuple[str, float]]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lower = str(key).lower()
            if isinstance(value, (int, float)) and any(part in lower for part in interesting):
                found.append((str(key), float(value)))
            elif isinstance(value, (dict, list)):
                _find_numeric_keys(value, interesting, found)
    elif isinstance(obj, list):
        for item in obj[:50]:
            _find_numeric_keys(item, interesting, found)


def _collect_agentsview_signal() -> Signal:
    binary = shutil.which("agentsview")
    if not binary:
        return Signal("agentsview", "unavailable", "agentsview not found", "info")
    code, stdout, stderr = _run_command([binary, "stats", "--format", "json"], timeout=8)
    if code is None:
        return Signal("agentsview", "unavailable", stderr or "agentsview unavailable", "info")
    if code != 0:
        return Signal("agentsview", "error", stderr[:240] or f"agentsview exited {code}", "warn")
    try:
        parsed = json.loads(stdout)
    except Exception:
        return Signal("agentsview", "observed", "stats command returned non-JSON output", "warn")

    numeric: list[tuple[str, float]] = []
    _find_numeric_keys(parsed, ("peak", "context", "cache", "token", "session"), numeric)
    top = sorted(numeric, key=lambda item: abs(item[1]), reverse=True)[:4]
    if top:
        detail = ", ".join(f"{key}={value:,.0f}" for key, value in top)
    else:
        detail = "stats JSON parsed; no obvious context/cache numeric keys found"
    return Signal("agentsview", "observed", detail, "info")


def _collect_ccusage_signal() -> Signal:
    binary = shutil.which("ccusage")
    if not binary:
        return Signal("ccusage", "unavailable", "ccusage not found", "info")
    code, stdout, stderr = _run_command([binary, "daily", "--json"], timeout=8)
    if code is None:
        return Signal("ccusage", "unavailable", stderr or "ccusage unavailable", "info")
    if code != 0:
        return Signal("ccusage", "error", stderr[:240] or f"ccusage exited {code}", "warn")
    try:
        parsed = json.loads(stdout)
    except Exception:
        return Signal("ccusage", "observed", "daily command returned non-JSON output", "warn")
    rows = parsed.get("daily") or parsed.get("data") or parsed.get("days") if isinstance(parsed, dict) else None
    if isinstance(rows, list):
        return Signal("ccusage", "observed", f"{len(rows)} daily usage rows available (historical spend signal only)", "info")
    return Signal("ccusage", "observed", "daily JSON parsed (historical spend signal only)", "info")


def _pick_recommendation(signals: list[Signal], intent: str) -> Recommendation:
    max_severity = max((_severity_rank(signal.severity) for signal in signals), default=0)
    red_names = {signal.name for signal in signals if signal.severity == "red"}
    warn_names = {signal.name for signal in signals if signal.severity == "warn"}

    if intent == "handover":
        return Recommendation("handover", "high", "handover intent was explicit", if_same_task="handover")
    if intent in {"new-task", "disposable"} and max_severity >= 1:
        return Recommendation("clear", "medium", "context is not worth preserving for a new/disposable task", if_same_task="compact")

    if red_names:
        reason = "red signal(s): " + ", ".join(sorted(red_names))
        return Recommendation("compact", "medium", reason, if_same_task="compact")
    if warn_names:
        reason = "warning signal(s): " + ", ".join(sorted(warn_names))
        return Recommendation("continue-with-checkpoint", "low", reason, if_same_task="compact if important context must be preserved")
    return Recommendation("continue", "medium", "no high-pressure signal found")


def _format_text_report(reco: Recommendation, signals: list[Signal], cwd: str, state_sessions: list[dict[str, Any]]) -> str:
    lines = [
        "Context Check",
        f"Recommendation: {reco.action} ({reco.confidence} confidence)",
        f"Reason: {reco.reason}",
        "",
        "Policy:",
        f"- Same task with useful context: {reco.if_same_task}",
        f"- New/disposable task: {reco.if_new_or_disposable}",
        f"- Cross-tool/tab transfer or poisoned context: {reco.if_cross_tool_or_poisoned}",
        "",
        "Evidence:",
    ]
    for signal in signals:
        lines.append(f"- {signal.name}: {signal.status}; {signal.detail}; severity={signal.severity}")
    if state_sessions:
        latest = state_sessions[0]
        last_prompt_at = latest.get("last_prompt_at")
        idle = "unknown"
        if isinstance(last_prompt_at, (int, float)):
            idle = f"{max(0.0, (_now() - float(last_prompt_at)) / 60.0):.1f}m"
        lines.extend(
            [
                "",
                "Local state:",
                f"- cwd: {cwd}",
                f"- matching sessions: {len(state_sessions)}",
                f"- latest turns: {latest.get('turns', 'unknown')}, idle: {idle}",
            ]
        )
    lines.append("")
    lines.append("Note: this is advisory; do not auto-run /clear, /compact, or $handover from the hook.")
    return "\n".join(lines)


def cmd_hook(args: argparse.Namespace) -> int:
    try:
        payload = _load_stdin_json()
        cwd = str(payload.get("cwd") or args.cwd or os.getcwd())
        now = _now()
        state = _read_state()
        signals, current = _collect_local_signals(payload, state, cwd, now, update=True)
        _write_state(state)

        severe = [signal for signal in signals if signal.severity in {"warn", "red"}]
        if not severe:
            return 0

        last_warning_at = float(current.get("last_warning_at") or 0)
        last_warning_turn = int(current.get("last_warning_turn") or 0)
        turns = int(current.get("turns") or 0)
        max_severity = max((_severity_rank(signal.severity) for signal in severe), default=0)
        last_rank = int(current.get("last_warning_rank") or 0)
        rate_limited = (now - last_warning_at) < HOOK_WARNING_INTERVAL_SECONDS and (turns - last_warning_turn) < HOOK_WARNING_INTERVAL_TURNS
        if rate_limited and max_severity <= last_rank:
            return 0

        reco = _pick_recommendation(signals, args.intent)
        reasons = "; ".join(f"{signal.name}: {signal.detail}" for signal in severe[:3])
        additional_context = (
            "CONTEXT-CHECK advisory: "
            f"recommendation={reco.action}, confidence={reco.confidence}. "
            f"Signals: {reasons}. "
            "Policy: continue if same-task cache/context is still useful; /compact if preserving this task matters; "
            "/clear if this is disposable or a new task; $handover only for Claude↔OMX/Codex transfer, poisoned context, or tab/session handoff. "
            "Do not auto-run these actions."
        )
        current["last_warning_at"] = now
        current["last_warning_turn"] = turns
        current["last_warning_rank"] = max_severity
        _write_state(state)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": additional_context,
                    }
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        # Claude hooks should fail open and stay silent.
        return 0
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    cwd = str(Path(args.cwd or os.getcwd()).expanduser())
    now = _now()
    state = _read_state()
    payload: dict[str, Any] = {"cwd": cwd}
    if args.prompt:
        payload["prompt"] = args.prompt
    local_signals, _ = _collect_local_signals(payload, state, cwd, now, update=False)

    signals = list(local_signals)
    if not args.local_only:
        signals.extend([_collect_headroom_signal(), _collect_agentsview_signal()])
        if args.include_ccusage:
            signals.append(_collect_ccusage_signal())

    sessions = _state_sessions_for_cwd(state, cwd)
    if sessions:
        latest = sessions[0]
        last_prompt_at = latest.get("last_prompt_at")
        if isinstance(last_prompt_at, (int, float)):
            idle = max(0.0, (now - float(last_prompt_at)) / 60.0)
            # A diagnose run often has only a cwd, while hook state is keyed by
            # prior concrete session IDs. Treat those same-cwd sessions as
            # historical evidence, not current-session pressure; otherwise an
            # old session in the same repo incorrectly forces `/compact`.
            severity = "info"
            if latest.get("key") == f"cwd:{cwd}":
                severity = "red" if idle >= IDLE_RED_MINUTES else "warn" if idle >= IDLE_WARN_MINUTES else "info"
            signals.append(Signal("stored_idle", "observed", f"latest stored prompt was {idle:.1f}m ago", severity))
        turns = int(latest.get("turns") or 0)
        severity = "red" if turns >= TURN_RED else "warn" if turns >= TURN_WARN else "info"
        signals.append(Signal("stored_turns", "observed", f"latest stored turn count is {turns}", severity))

    reco = _pick_recommendation(signals, args.intent)
    if args.json:
        print(
            json.dumps(
                {
                    "recommendation": asdict(reco),
                    "signals": [asdict(signal) for signal in signals],
                    "cwd": cwd,
                    "matching_state_sessions": len(sessions),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_format_text_report(reco, signals, cwd, sessions))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Advisory context/cache decision helper for Claude, Codex, and OMX.")
    sub = parser.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook", help="cheap UserPromptSubmit hook mode; reads JSON payload on stdin")
    hook.add_argument("--cwd", default=None)
    hook.add_argument("--intent", choices=["current", "new-task", "disposable", "handover"], default="current")
    hook.set_defaults(func=cmd_hook)

    diagnose = sub.add_parser("diagnose", help="manual diagnosis; may call agentsview and ccusage when installed")
    diagnose.add_argument("--cwd", default=None)
    diagnose.add_argument("--intent", choices=["current", "new-task", "disposable", "handover"], default="current")
    diagnose.add_argument("--prompt", default="", help="optional prompt text to include in prompt-size analysis")
    diagnose.add_argument("--local-only", action="store_true", help="skip agentsview/ccusage probes")
    diagnose.add_argument("--include-ccusage", action="store_true", help="also run ccusage; slower and historical, so disabled by default")
    diagnose.add_argument("--json", action="store_true")
    diagnose.set_defaults(func=cmd_diagnose)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
