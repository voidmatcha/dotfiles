#!/usr/bin/env python3
"""Summarize RTK compression safety signals without storing raw commands/output.

The script accepts privacy-preserving JSONL events and can also include the coarse
`rtk gain --history --format json` summary. Event records may be produced by RTK
hook-audit or by a future wrapper, but this reporter only emits hashes, families,
counts, and token totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
DEFAULT_EVENT_PATHS = [
    HOME / ".local/share/rtk/safety-events.jsonl",
    HOME / ".local/share/rtk/hook-audit.log",
]


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        # Treat large numbers as milliseconds.
        if value > 10_000_000_000:
            value = value / 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_duration(value: str | None) -> timedelta | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d+)([dhm])", value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def _cutoff(since: str | None) -> datetime | None:
    duration = _parse_duration(since)
    if duration is not None:
        return datetime.now(timezone.utc) - duration
    return _parse_ts(since)


def _command_family(command: str) -> str:
    parts = re.split(r"\s+", command.strip())
    if not parts or not parts[0]:
        return "unknown"
    if parts[0] == "rtk" and len(parts) >= 2:
        return " ".join(parts[:3]) if len(parts) >= 3 and parts[1] in {"git", "gh", "pnpm", "npm"} else " ".join(parts[:2])
    return " ".join(parts[:2]) if len(parts) >= 2 else parts[0]


@dataclass
class Event:
    ts: datetime | None = None
    status: str = "unknown"
    command_family: str = "unknown"
    command_hash: str = "sha256:unknown"
    cwd_hash: str = "sha256:unknown"
    raw_tokens: int = 0
    delivered_tokens: int = 0
    saved_tokens: int = 0
    exit_code: int | None = None
    duration_ms: int = 0
    source: str = "event"

    @property
    def compression_ratio(self) -> float:
        if self.raw_tokens <= 0:
            return 0.0
        return max(0.0, min(1.0, self.saved_tokens / self.raw_tokens))


def _normalize_status(value: Any, raw: dict[str, Any] | None = None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"compressed", "compress", "rewritten", "rewrite", "filtered"}:
        return "compressed"
    if text in {"passthrough", "pass_through", "passed", "unchanged"}:
        return "passthrough"
    if text in {"fallback", "failed_open", "fail_open"}:
        return "fallback"
    if text in {"bypass", "proxy", "explicit_bypass"}:
        return "bypass"
    if text in {"error", "failed", "failure"}:
        return "error"
    if raw:
        command = " ".join(str(raw.get(key, "")) for key in ("command", "original", "rewritten"))
        lowered = command.lower()
        if "rtk proxy" in lowered:
            return "bypass"
        if raw.get("saved_tokens") or raw.get("saved"):
            return "compressed"
    return text or "unknown"


def _event_from_json(obj: dict[str, Any], source: str) -> Event:
    command = str(obj.get("command") or obj.get("original") or obj.get("rewritten") or "")
    raw_tokens = _to_int(obj.get("raw_tokens") or obj.get("input_tokens") or obj.get("raw"))
    delivered_tokens = _to_int(obj.get("delivered_tokens") or obj.get("output_tokens") or obj.get("delivered"))
    saved_tokens = _to_int(obj.get("saved_tokens") or obj.get("saved"))
    if saved_tokens == 0 and raw_tokens and delivered_tokens:
        saved_tokens = max(0, raw_tokens - delivered_tokens)
    command_hash = str(obj.get("command_hash") or "")
    if not command_hash:
        command_hash = _hash_text(command or str(obj.get("command_family") or "unknown"))
    cwd_hash = str(obj.get("cwd_hash") or "")
    if not cwd_hash:
        cwd = str(obj.get("cwd") or obj.get("repo") or "unknown")
        cwd_hash = _hash_text(cwd)
    return Event(
        ts=_parse_ts(obj.get("ts") or obj.get("timestamp") or obj.get("time")),
        status=_normalize_status(obj.get("status") or obj.get("action") or obj.get("outcome"), obj),
        command_family=str(obj.get("command_family") or _command_family(command)),
        command_hash=command_hash,
        cwd_hash=cwd_hash,
        raw_tokens=raw_tokens,
        delivered_tokens=delivered_tokens,
        saved_tokens=saved_tokens,
        exit_code=None if obj.get("exit_code") is None else _to_int(obj.get("exit_code")),
        duration_ms=_to_int(obj.get("duration_ms") or obj.get("duration")),
        source=source,
    )


def _event_from_text(line: str, source: str) -> Event:
    lowered = line.lower()
    status = "unknown"
    for candidate in ("fallback", "bypass", "passthrough", "compressed", "error"):
        if candidate in lowered:
            status = candidate
            break
    raw = re.search(r"raw[_ =:]+(\d+)", lowered)
    delivered = re.search(r"(?:delivered|output)[_ =:]+(\d+)", lowered)
    saved = re.search(r"saved[_ =:]+(\d+)", lowered)
    return Event(
        ts=None,
        status=status,
        command_family="hook-audit-text",
        command_hash=_hash_text(line),
        cwd_hash="sha256:unknown",
        raw_tokens=_to_int(raw.group(1) if raw else None),
        delivered_tokens=_to_int(delivered.group(1) if delivered else None),
        saved_tokens=_to_int(saved.group(1) if saved else None),
        source=source,
    )


def read_events(paths: list[Path], cutoff_ts: datetime | None) -> tuple[list[Event], list[str]]:
    events: list[Event] = []
    notes: list[str] = []
    for path in paths:
        expanded = path.expanduser()
        if not expanded.exists():
            notes.append(f"missing event log: {expanded}")
            continue
        count = 0
        dropped_no_ts = 0
        with expanded.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    event = _event_from_text(line, expanded.name)
                else:
                    if not isinstance(parsed, dict):
                        continue
                    event = _event_from_json(parsed, expanded.name)
                if cutoff_ts and event.ts is None:
                    # Honor the --since window: ts-less records cannot be placed in
                    # time, so drop them rather than counting the whole history.
                    dropped_no_ts += 1
                    continue
                if cutoff_ts and event.ts and event.ts < cutoff_ts:
                    continue
                events.append(event)
                count += 1
        notes.append(f"loaded {count} event(s): {expanded}")
        if dropped_no_ts:
            notes.append(
                f"dropped {dropped_no_ts} event(s) with no timestamp from {expanded.name} "
                "(excluded by --since window; text-format hook-audit logs have no per-event ts)"
            )
    return events, notes


def read_rtk_gain() -> tuple[dict[str, Any] | None, str | None]:
    try:
        proc = subprocess.run(
            ["rtk", "gain", "--history", "--format", "json"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"rtk gain unavailable: {exc}"
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()[:300]
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, "rtk gain returned non-JSON output"
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return None, "rtk gain JSON did not contain summary"
    return summary, None


@dataclass
class SafetySummary:
    total_events: int
    status_counts: Counter[str]
    raw_tokens: int
    delivered_tokens: int
    saved_tokens: int
    high_compression_events: int
    repeat_candidates: int
    top_families: list[tuple[str, int]] = field(default_factory=list)


def summarize_events(events: list[Event], high_threshold: float, repeat_window: timedelta) -> SafetySummary:
    status_counts = Counter(event.status for event in events)
    raw_tokens = sum(event.raw_tokens for event in events)
    delivered_tokens = sum(event.delivered_tokens for event in events)
    saved_tokens = sum(event.saved_tokens for event in events)
    high_events = [event for event in events if event.compression_ratio >= high_threshold]
    high_count = len(high_events)

    repeat_candidates = 0
    last_high_by_key: dict[tuple[str, str], datetime] = {}
    sorted_events = sorted((event for event in events if event.ts is not None), key=lambda item: item.ts or datetime.min.replace(tzinfo=timezone.utc))
    for event in sorted_events:
        assert event.ts is not None
        key = (event.cwd_hash, event.command_hash)
        prior = last_high_by_key.get(key)
        if prior and prior < event.ts <= prior + repeat_window:
            repeat_candidates += 1
            # Avoid counting a burst of repeats after the same high-compression event more than once.
            last_high_by_key.pop(key, None)
        if event.compression_ratio >= high_threshold and event.status == "compressed":
            last_high_by_key[key] = event.ts

    families = Counter(event.command_family for event in events)
    return SafetySummary(
        total_events=len(events),
        status_counts=status_counts,
        raw_tokens=raw_tokens,
        delivered_tokens=delivered_tokens,
        saved_tokens=saved_tokens,
        high_compression_events=high_count,
        repeat_candidates=repeat_candidates,
        top_families=families.most_common(8),
    )


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _fmt_pct(part: int, whole: int) -> str:
    if whole <= 0:
        return "n/a"
    return f"{(part / whole) * 100:.2f}%"


def render_markdown(summary: SafetySummary, gain: dict[str, Any] | None, notes: list[str], since: str, high_threshold: float) -> str:
    lines = [
        "# RTK safety summary",
        "",
        f"Window: `{since}`",
        f"High-compression threshold: `{high_threshold:.0%}` saved/raw",
        "",
        "## Event safety counters",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Events loaded | {_fmt_int(summary.total_events)} |",
        f"| Compressed | {_fmt_int(summary.status_counts.get('compressed', 0))} |",
        f"| Passthrough | {_fmt_int(summary.status_counts.get('passthrough', 0))} |",
        f"| Fallback | {_fmt_int(summary.status_counts.get('fallback', 0))} ({_fmt_pct(summary.status_counts.get('fallback', 0), summary.total_events)}) |",
        f"| Explicit bypass | {_fmt_int(summary.status_counts.get('bypass', 0))} ({_fmt_pct(summary.status_counts.get('bypass', 0), summary.total_events)}) |",
        f"| Error | {_fmt_int(summary.status_counts.get('error', 0))} ({_fmt_pct(summary.status_counts.get('error', 0), summary.total_events)}) |",
        f"| High-compression events | {_fmt_int(summary.high_compression_events)} |",
        f"| Repeat-after-compression candidates | {_fmt_int(summary.repeat_candidates)} |",
        "",
        "## Token counters from events",
        "",
        "| Metric | Tokens |",
        "| --- | ---: |",
        f"| Raw output | {_fmt_int(summary.raw_tokens)} |",
        f"| Delivered output | {_fmt_int(summary.delivered_tokens)} |",
        f"| Saved output | {_fmt_int(summary.saved_tokens)} ({_fmt_pct(summary.saved_tokens, summary.raw_tokens)}) |",
    ]
    if summary.top_families:
        lines.extend(["", "## Top command families", "", "| Family | Events |", "| --- | ---: |"])
        for family, count in summary.top_families:
            lines.append(f"| `{family}` | {_fmt_int(count)} |")
    if gain:
        lines.extend([
            "",
            "## RTK gain summary",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Commands | {_fmt_int(_to_int(gain.get('total_commands')))} |",
            f"| Raw output | {_fmt_int(_to_int(gain.get('total_input')))} |",
            f"| Delivered output | {_fmt_int(_to_int(gain.get('total_output')))} |",
            f"| Saved output | {_fmt_int(_to_int(gain.get('total_saved')))} |",
            f"| Average savings | {float(gain.get('avg_savings_pct') or 0):.2f}% |",
        ])
    lines.extend([
        "",
        "## Interpretation boundaries",
        "",
        "- Repeat-after-compression is a candidate signal: same hashed command and cwd within the repeat window after a high-compression event. It is not causal proof.",
        "- Repeat-after-compression detection requires JSONL-format events; text-format hook-audit logs supply no per-command timestamps/families, so this counter is structurally 0 for text-only sources.",
        "- Event logs must not store raw command output, prompts, paths, repo names, or company/client names.",
        "- RTK gain is a tool-output compression metric, not a total-cost-saved metric.",
    ])
    if notes:
        lines.extend(["", "## Data-source notes", ""])
        for note in notes:
            lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_json(summary: SafetySummary, gain: dict[str, Any] | None, notes: list[str], since: str, high_threshold: float) -> str:
    payload = {
        "since": since,
        "high_compression_threshold": high_threshold,
        "events": {
            "total": summary.total_events,
            "status_counts": dict(summary.status_counts),
            "raw_tokens": summary.raw_tokens,
            "delivered_tokens": summary.delivered_tokens,
            "saved_tokens": summary.saved_tokens,
            "high_compression_events": summary.high_compression_events,
            "repeat_after_compression_candidates": summary.repeat_candidates,
            "top_command_families": summary.top_families,
        },
        "rtk_gain_summary": gain,
        "notes": notes,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report RTK compression safety signals")
    parser.add_argument("--events", action="append", type=Path, help="privacy-preserving RTK event JSONL/log path; can be repeated")
    parser.add_argument("--since", default="30d", help="window such as 30d, 24h, 60m, or ISO timestamp")
    parser.add_argument("--repeat-window", default="10m", help="rerun candidate window after high compression")
    parser.add_argument("--high-threshold", type=float, default=0.90, help="saved/raw ratio considered high compression")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--no-rtk-gain", action="store_true", help="do not invoke `rtk gain --history --format json`")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event_paths = args.events or DEFAULT_EVENT_PATHS
    cutoff_ts = _cutoff(args.since)
    repeat_window = _parse_duration(args.repeat_window) or timedelta(minutes=10)
    events, notes = read_events(event_paths, cutoff_ts)
    if args.since and cutoff_ts is None:
        notes.append(
            f"could not parse --since {args.since!r} (expected NNd/NNh/NNm or ISO timestamp); "
            "reporting all-time with no window applied"
        )
    gain = None
    if not args.no_rtk_gain:
        gain, error = read_rtk_gain()
        if error:
            notes.append(error)
    summary = summarize_events(events, args.high_threshold, repeat_window)
    if args.format == "json":
        sys.stdout.write(render_json(summary, gain, notes, args.since, args.high_threshold))
    else:
        sys.stdout.write(render_markdown(summary, gain, notes, args.since, args.high_threshold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
