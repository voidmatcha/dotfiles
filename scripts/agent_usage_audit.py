#!/usr/bin/env python3
"""Summarize local agent/skill install and usage signals without dumping transcripts."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
REPO_DEFAULT = Path(__file__).resolve().parents[1]
DEFAULT_RTK_EVENT_PATHS = (
    HOME / ".local/share/rtk/safety-events.jsonl",
    HOME / ".local/share/rtk/hook-audit.log",
)
TOKEN_KEYS = {
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "cached_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "reasoning_output_tokens",
    "total_tokens",
}
USAGE_NODE_NAMES = {"usage", "token_usage", "usage_metadata", "total_token_usage"}


def rel(path: Path) -> str:
    try:
        return "~" + str(path.expanduser()).removeprefix(str(HOME))
    except Exception:
        return str(path)


def exists_marker(path: Path) -> str:
    return "OK" if path.exists() or path.is_symlink() else "MISSING"


def local_agent_names(repo: Path) -> list[str]:
    return [path.stem for path in sorted((repo / "configs/agents").glob("*.md"))]


def local_skill_names(repo: Path) -> list[str]:
    skills_root = repo / "plugins/local-skills/skills"
    return [path.parent.name for path in sorted(skills_root.glob("*/SKILL.md"))]


def scan_usage(names: list[str], projects: Path | None = None) -> tuple[int, Counter[str], Counter[str]]:
    projects = projects or HOME / ".claude/projects"
    name_hits: Counter[str] = Counter()
    path_hits: Counter[str] = Counter()
    if not projects.exists():
        return 0, name_hits, path_hits
    files = sorted(projects.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
    patterns = {name: re.compile(rf"(?i)(?<![\w-]){re.escape(name)}(?![\w-])") for name in names}
    max_bytes = 2_000_000
    for path in files:
        try:
            handle = path.open("rb")
        except OSError:
            continue
        with handle:
            text = handle.read(max_bytes).decode("utf-8", errors="ignore")
        for name, pattern in patterns.items():
            count = len(pattern.findall(text))
            if count:
                name_hits[name] += count
                path_hits[rel(path)] += count
        if "subagents/" in text:
            name_hits["subagents/"] += text.count("subagents/")
    return len(files), name_hits, path_hits


def print_default_audit(repo: Path) -> int:
    agents = local_agent_names(repo)
    skills = local_skill_names(repo)
    names = agents + skills + ["orchestrate"]
    scanned, name_hits, path_hits = scan_usage(names)

    print("# Agent usage audit")
    print()
    print(f"Repo: {repo}")
    print(f"Claude projects dir: {exists_marker(HOME / '.claude/projects')}")
    print(f"Codex sessions dir: {exists_marker(HOME / '.codex/sessions')}")
    print()
    print(f"Local agents ({len(agents)}):")
    for name in agents:
        print(f"- {name}")
    print()
    print(f"Local skills ({len(skills)}):")
    for name in skills:
        print(f"- {name}")
    print()
    print(f"Recent Claude JSONL files scanned: {scanned}")
    print()
    print("Observed references:")
    if not name_hits:
        print("- none in the scanned window")
    else:
        for name, count in name_hits.most_common(30):
            print(f"- {name}: {count}")
    print()
    print("Files with references:")
    if not path_hits:
        print("- none")
    else:
        for path, count in path_hits.most_common(10):
            print(f"- {path}: {count}")
    print()
    print("Notes:")
    print("- Counts are references, not successful task outcomes.")
    print("- Use them to prioritize follow-up checks, not as the sole install/prune decision.")
    print("- Run `python3 scripts/agent_usage_audit.py session-report --since 7d` for token pressure by source.")
    return 0


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


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
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


def _cutoff(since: str) -> datetime | None:
    duration = _parse_duration(since)
    if duration:
        return datetime.now(timezone.utc) - duration
    return _parse_ts(since)


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return max(1, math.ceil(len(value) / 4)) if value else 0
    if isinstance(value, (int, float, bool)):
        return max(1, math.ceil(len(str(value)) / 4))
    try:
        return max(1, math.ceil(len(json.dumps(value, ensure_ascii=False)) / 4))
    except TypeError:
        return max(1, math.ceil(len(str(value)) / 4))


def _iter_jsonl_files(root: Path, cutoff_ts: datetime | None, max_files: int) -> list[Path]:
    if not root.exists():
        return []
    candidates = sorted(root.rglob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    if cutoff_ts:
        cutoff_epoch = cutoff_ts.timestamp()
        candidates = [path for path in candidates if path.stat().st_mtime >= cutoff_epoch]
    return candidates[:max_files]


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _walk_with_path(value: Any, path: str = ""):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk_with_path(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_with_path(child, f"{path}[{index}]")


def _usage_nodes(obj: Any) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for path, node in _walk_with_path(obj):
        if not (set(node) & TOKEN_KEYS):
            continue
        leaf = path.rsplit("/", 1)[-1]
        if leaf in USAGE_NODE_NAMES:
            found.append((path, node))
    return found

def _usage_total(node: dict[str, Any]) -> int:
    # Count only direct scalar token fields. Nested per-iteration arrays are often
    # diagnostic or duplicated details and must not be recursively summed.
    direct_scalar_keys = [
        key
        for key in TOKEN_KEYS
        if key != "total_tokens" and isinstance(node.get(key), (int, float, str))
    ]
    if direct_scalar_keys:
        return sum(_to_int(node.get(key)) for key in direct_scalar_keys)
    return _to_int(node.get("total_tokens"))


def _tool_name(node: dict[str, Any]) -> str:
    for key in ("tool_name", "name", "recipient_name", "server", "mcp_server", "mcp_server_name"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _classify_tool(name: str) -> str:
    lowered = name.lower()
    if "mcp__codegraph" in lowered or "codegraph" in lowered:
        return "MCP: codegraph"
    if "mcp__serena" in lowered or "serena" in lowered:
        return "MCP: serena"
    if "chrome_devtools" in lowered or "chrome-devtools" in lowered or "browser" in lowered:
        return "Browser / Chrome DevTools"
    if "figma" in lowered:
        return "Figma"
    if lowered in {"bash", "shell"} or "exec_command" in lowered:
        return "Shell tool output"
    if "task" in lowered or "subagent" in lowered or "agent" in lowered:
        return "Subagents"
    if "mcp__" in lowered:
        return "MCP: other"
    return "Tool results: other"


def _tool_result_tokens(node: dict[str, Any]) -> int:
    if "result" in node:
        return _estimate_tokens(node.get("result"))
    if "output" in node:
        return _estimate_tokens(node.get("output"))
    if "content" in node:
        return _estimate_tokens(node.get("content"))
    if "text" in node:
        return _estimate_tokens(node.get("text"))
    return 0


def _looks_like_tool_result(node: dict[str, Any]) -> bool:
    node_type = str(node.get("type") or node.get("event") or "").lower()
    if node_type in {"tool_result", "function_call_output", "tool_call_output"}:
        return True
    if node.get("tool_name") or node.get("recipient_name"):
        return any(key in node for key in ("result", "output", "content", "text"))
    return False


@dataclass
class SourceRow:
    source: str
    calls: int = 0
    exact_tokens: int = 0
    estimated_tokens: int = 0
    notes: Counter[str] = field(default_factory=Counter)


def _row(rows: dict[str, SourceRow], source: str) -> SourceRow:
    if source not in rows:
        rows[source] = SourceRow(source=source)
    return rows[source]


def parse_rtk_events(paths: list[Path], cutoff_ts: datetime | None, rows: dict[str, SourceRow]) -> list[str]:
    notes: list[str] = []
    for path in paths:
        expanded = path.expanduser()
        if not expanded.exists():
            notes.append(f"missing RTK events: {expanded}")
            continue

        loaded = 0
        no_ts_counted = 0
        raw_total = delivered_total = saved_total = 0
        status_counts: Counter[str] = Counter()
        with expanded.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                ts = _parse_ts(obj.get("ts") or obj.get("timestamp"))
                if cutoff_ts and ts and ts < cutoff_ts:
                    continue
                if cutoff_ts and ts is None:
                    # No file-mtime pre-filter on RTK event logs, so ts-less records
                    # are counted regardless of --since; surface that in a note.
                    no_ts_counted += 1
                raw = _to_int(obj.get("raw_tokens") or obj.get("input_tokens") or obj.get("raw"))
                delivered = _to_int(obj.get("delivered_tokens") or obj.get("output_tokens") or obj.get("delivered"))
                saved = _to_int(obj.get("saved_tokens") or obj.get("saved"))
                if not saved and raw and delivered:
                    saved = max(0, raw - delivered)
                status = str(obj.get("status") or obj.get("action") or "unknown").lower()
                status_counts[status] += 1
                loaded += 1
                raw_total += raw
                delivered_total += delivered
                saved_total += saved

        if loaded:
            row = _row(rows, "Bash / RTK")
            row.calls += loaded
            row.exact_tokens += delivered_total
            if raw_total:
                row.notes[f"{expanded.name}: raw {_compact(raw_total)}, saved {_compact(saved_total)}"] += 1
            for status, count in status_counts.items():
                row.notes[f"{expanded.name}: {status} {count}"] += 1
        notes.append(f"loaded {loaded} RTK event(s): {expanded}")
        if no_ts_counted:
            notes.append(
                f"{no_ts_counted} RTK event(s) in {expanded.name} had no timestamp; "
                "counted regardless of --since window"
            )
    return notes

def parse_agent_jsonl(root: Path, cutoff_ts: datetime | None, max_files: int, rows: dict[str, SourceRow], usage_source: str) -> list[str]:
    notes: list[str] = []
    files = _iter_jsonl_files(root.expanduser(), cutoff_ts, max_files)
    if not files:
        notes.append(f"no {usage_source} JSONL files in window: {root.expanduser()}")
        return notes
    usage_seen = 0
    tool_seen = 0
    no_ts_counted = 0
    cumulative_seen: dict[str, int] = {}
    for path in files:
        try:
            handle = path.open("r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record_ts = _parse_ts(obj.get("timestamp") or obj.get("ts") or obj.get("created_at")) if isinstance(obj, dict) else None
                if cutoff_ts and record_ts and record_ts < cutoff_ts:
                    continue
                if cutoff_ts and record_ts is None:
                    # File was kept by the mtime pre-filter, so a ts-less record is
                    # plausibly in-window; count it but track for an honesty note.
                    no_ts_counted += 1
                for usage_path, usage in _usage_nodes(obj):
                    if usage_path.endswith("/total_token_usage"):
                        current = _to_int(usage.get("total_tokens")) or _usage_total(usage)
                        key = f"{path}:{usage_path}"
                        previous = cumulative_seen.get(key, 0)
                        total = max(0, current - previous) if current >= previous else current
                        cumulative_seen[key] = max(previous, current)
                    else:
                        total = _usage_total(usage)
                    if total:
                        row = _row(rows, f"{usage_source} usage")
                        row.calls += 1
                        row.exact_tokens += total
                        usage_seen += 1
                for node in _walk(obj):
                    if not _looks_like_tool_result(node):
                        continue
                    estimated = _tool_result_tokens(node)
                    if not estimated:
                        continue
                    source = _classify_tool(_tool_name(node))
                    row = _row(rows, source)
                    row.calls += 1
                    row.estimated_tokens += estimated
                    row.notes[f"from {usage_source}"] += 1
                    tool_seen += 1
    notes.append(f"scanned {len(files)} {usage_source} file(s); usage records {usage_seen}; tool results {tool_seen}")
    if no_ts_counted:
        notes.append(
            f"{no_ts_counted} {usage_source} record(s) had no timestamp; counted regardless of --since "
            "(mitigated by per-file mtime pre-filter, so likely in-window)"
        )
    return notes


def _compact(value: int) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def render_session_markdown(rows: dict[str, SourceRow], notes: list[str], since: str) -> str:
    ordered = sorted(rows.values(), key=lambda row: (row.exact_tokens + row.estimated_tokens, row.calls), reverse=True)
    lines = [
        "# Agent usage source report",
        "",
        f"Window: `{since}`",
        "",
        "| Source | Calls | Exact tokens | Estimated tool-result tokens | Notes |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    if not ordered:
        lines.append("| No local source rows found | 0 | 0 | 0 | Check data-source notes |")
    for row in ordered:
        note_text = "; ".join(note for note, _ in row.notes.most_common(3)) or ""
        lines.append(
            f"| {row.source} | {row.calls:,} | {row.exact_tokens:,} | {row.estimated_tokens:,} | {note_text} |"
        )
    exact_total = sum(row.exact_tokens for row in ordered)
    estimate_total = sum(row.estimated_tokens for row in ordered)
    lines.extend([
        "",
        "## Totals",
        "",
        f"- Exact tokens from provider/log counters: `{exact_total:,}`",
        f"- Estimated tool-result pressure: `{estimate_total:,}`",
        "",
        "## Interpretation boundaries",
        "",
        "- Exact tokens come from provider/local usage counters or RTK event counters.",
        "- Estimated tool-result pressure uses a conservative characters/4 heuristic for log payloads.",
        "- This report identifies pressure sources; it does not assign exact total spend to a single tool.",
        "- The report does not print prompts, raw command output, file paths, or transcript text.",
    ])
    if notes:
        lines.extend(["", "## Data-source notes", ""])
        for note in notes:
            lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_session_json(rows: dict[str, SourceRow], notes: list[str], since: str) -> str:
    payload = {
        "since": since,
        "sources": [
            {
                "source": row.source,
                "calls": row.calls,
                "exact_tokens": row.exact_tokens,
                "estimated_tool_result_tokens": row.estimated_tokens,
                "notes": dict(row.notes),
            }
            for row in sorted(rows.values(), key=lambda item: item.source)
        ],
        "totals": {
            "exact_tokens": sum(row.exact_tokens for row in rows.values()),
            "estimated_tool_result_tokens": sum(row.estimated_tokens for row in rows.values()),
        },
        "notes": notes,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def session_report(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Report local token pressure by agent/tool source")
    parser.add_argument("--since", default="7d", help="window such as 7d, 24h, 60m, or ISO timestamp")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    parser.add_argument("--rtk-events", action="append", type=Path, default=None, help="RTK event JSONL/log path; repeatable. Defaults to RTK safety-events then hook-audit.")
    parser.add_argument("--claude-dir", type=Path, default=HOME / ".claude/projects")
    parser.add_argument("--codex-dir", type=Path, default=HOME / ".codex/sessions")
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--redact", action="store_true", help="kept for CLI clarity; output is redacted by design")
    args = parser.parse_args(argv)

    cutoff_ts = _cutoff(args.since)
    rows: dict[str, SourceRow] = {}
    notes: list[str] = []
    if args.since and cutoff_ts is None:
        notes.append(
            f"could not parse --since {args.since!r} (expected NNd/NNh/NNm or ISO timestamp); "
            "reporting all-time with no window applied"
        )
    notes.extend(parse_rtk_events(args.rtk_events or list(DEFAULT_RTK_EVENT_PATHS), cutoff_ts, rows))
    notes.extend(parse_agent_jsonl(args.claude_dir, cutoff_ts, args.max_files, rows, "Claude"))
    notes.extend(parse_agent_jsonl(args.codex_dir, cutoff_ts, args.max_files, rows, "Codex"))

    if args.format == "json":
        sys.stdout.write(render_session_json(rows, notes, args.since))
    else:
        sys.stdout.write(render_session_markdown(rows, notes, args.since))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "session-report":
        return session_report(argv[1:])
    if argv and argv[0] == "audit":
        argv = argv[1:]

    parser = argparse.ArgumentParser(description="Audit installed local agent/skill usage signals.")
    parser.add_argument("repo", nargs="?", type=Path, default=REPO_DEFAULT)
    args = parser.parse_args(argv)
    return print_default_audit(args.repo.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
