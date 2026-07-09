#!/usr/bin/env python3
"""Check local code intelligence wiring for codegraph/serena/MCP."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover - macOS system Python
        tomllib = None


REPO = Path(__file__).resolve().parents[1]
CODEGRAPH_TIMEOUT_SECONDS = 15
PENDING_CHANGE_KEYS = ("added", "modified", "removed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose codegraph/serena commands, MCP configuration, and "
            "per-repository indexes."
        )
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="target repository directory (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit a machine-readable JSON report",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any command, config, index, or status check is unhealthy",
    )
    return parser


def resolve_target(parser: argparse.ArgumentParser, value: str) -> Path:
    target = Path(value).expanduser().resolve()
    if not target.exists():
        parser.error(f"target repository does not exist: {target}")
    if not target.is_dir():
        parser.error(f"target repository is not a directory: {target}")
    return target


def mark(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def has_toml_server(path: Path, name: str) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text()
    except (OSError, ValueError, TypeError):
        return False
    if tomllib is None:
        # The doctor must remain usable with the dependency-free macOS system
        # Python. Full TOML validation belongs to verify.sh; here we only need
        # a conservative table-presence check for the two MCP server names.
        escaped = re.escape(name)
        table = re.compile(
            rf"^\[\s*mcp_servers\.(?:{escaped}|\"{escaped}\"|'{escaped}')"
            rf"(?:\.[^\]]+)?\s*\]$"
        )
        return any(
            table.match(line.split("#", 1)[0].strip())
            for line in text.splitlines()
        )
    try:
        data = tomllib.loads(text)
    except (ValueError, TypeError):
        return False
    servers = data.get("mcp_servers", {})
    return isinstance(servers, dict) and name in servers


def has_json_server(path: Path, name: str) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    servers = data.get("mcpServers", {})
    return isinstance(servers, dict) and name in servers


def add_issue(
    issues: list[dict[str, str]],
    code: str,
    message: str,
) -> None:
    issues.append({"code": code, "message": message})


def unknown_codegraph_status() -> dict[str, Any]:
    return {
        "checked": False,
        "commandOk": None,
        "reindexRecommended": None,
        "pendingChanges": None,
        "pendingChangeCount": None,
        "worktreeMismatch": None,
        "worktreeMismatchKnown": False,
        "error": None,
    }


def parse_codegraph_status(
    payload: object,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    """Parse status fields without treating unknown shapes as healthy."""
    status = unknown_codegraph_status()
    status.update({"checked": True, "commandOk": True})

    if not isinstance(payload, dict):
        message = "codegraph status JSON must be an object"
        status.update({"commandOk": False, "error": message})
        add_issue(issues, "codegraph_status_invalid", message)
        return status

    index = payload.get("index")
    reindex_value: object = None
    reindex_known = False
    if isinstance(index, dict) and "reindexRecommended" in index:
        reindex_value = index["reindexRecommended"]
        reindex_known = isinstance(reindex_value, bool)
    elif "reindexRecommended" in payload:
        # Accept the top-level shape used by some older codegraph releases.
        reindex_value = payload["reindexRecommended"]
        reindex_known = isinstance(reindex_value, bool)

    if reindex_known:
        status["reindexRecommended"] = reindex_value
        if reindex_value is True:
            add_issue(
                issues,
                "codegraph_reindex_recommended",
                "codegraph recommends rebuilding the target repository index",
            )
    else:
        add_issue(
            issues,
            "codegraph_reindex_unknown",
            "codegraph status did not provide a boolean reindexRecommended value",
        )

    pending = payload.get("pendingChanges")
    pending_known = isinstance(pending, dict) and all(
        key in pending
        and isinstance(pending[key], int)
        and not isinstance(pending[key], bool)
        and pending[key] >= 0
        for key in PENDING_CHANGE_KEYS
    )
    if pending_known:
        normalized_pending = {key: pending[key] for key in PENDING_CHANGE_KEYS}
        pending_count = sum(normalized_pending.values())
        status["pendingChanges"] = normalized_pending
        status["pendingChangeCount"] = pending_count
        if pending_count:
            add_issue(
                issues,
                "codegraph_pending_changes",
                f"codegraph reports {pending_count} pending file change(s)",
            )
    else:
        add_issue(
            issues,
            "codegraph_pending_changes_unknown",
            "codegraph status did not provide non-negative pendingChanges counts",
        )

    if "worktreeMismatch" in payload:
        mismatch = payload["worktreeMismatch"]
        status["worktreeMismatch"] = mismatch
        status["worktreeMismatchKnown"] = True
        if mismatch is not None and mismatch is not False:
            add_issue(
                issues,
                "codegraph_worktree_mismatch",
                "codegraph reports that its index belongs to another worktree",
            )
    else:
        add_issue(
            issues,
            "codegraph_worktree_mismatch_unknown",
            "codegraph status did not provide worktreeMismatch",
        )

    return status


def inspect_codegraph(
    executable: str,
    target: Path,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    status = unknown_codegraph_status()
    status["checked"] = True
    try:
        result = subprocess.run(
            [executable, "status", "--json", str(target)],
            text=True,
            capture_output=True,
            check=False,
            timeout=CODEGRAPH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        message = (
            f"codegraph status timed out after {CODEGRAPH_TIMEOUT_SECONDS} seconds"
        )
        status.update({"commandOk": False, "error": message})
        add_issue(issues, "codegraph_status_timeout", message)
        return status
    except OSError as exc:
        message = f"could not run codegraph status: {exc}"
        status.update({"commandOk": False, "error": message})
        add_issue(issues, "codegraph_status_failed", message)
        return status

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        message = f"codegraph status exited {result.returncode}: {detail[:500]}"
        status.update({"commandOk": False, "error": message})
        add_issue(issues, "codegraph_status_failed", message)
        return status

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        message = f"codegraph status returned invalid JSON: {exc.msg}"
        status.update({"commandOk": False, "error": message})
        add_issue(issues, "codegraph_status_invalid_json", message)
        return status

    return parse_codegraph_status(payload, issues)


def build_report(target: Path) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    command_paths = {
        name: shutil.which(name)
        for name in ("codegraph", "serena", "codex", "claude")
    }
    commands: dict[str, dict[str, object]] = {}
    for name, path in command_paths.items():
        available = bool(path)
        commands[name] = {"available": available, "path": path}
        if not available:
            add_issue(
                issues,
                f"command_{name}_missing",
                f"required command is unavailable: {name}",
            )

    codex_cfg = REPO / "configs/codex/config.toml"
    claude_mcp = REPO / "configs/mcp.json"
    live_codex = Path.home() / ".codex/config.toml"
    config: dict[str, dict[str, bool]] = {
        "sourceCodex": {},
        "sourceClaude": {},
        "liveCodex": {},
    }
    for server in ("codegraph", "serena"):
        config_checks = (
            ("sourceCodex", has_toml_server(codex_cfg, server)),
            ("sourceClaude", has_json_server(claude_mcp, server)),
            ("liveCodex", has_toml_server(live_codex, server)),
        )
        for location, present in config_checks:
            config[location][server] = present
            if not present:
                add_issue(
                    issues,
                    f"config_{location}_{server}_missing",
                    f"{location} config is missing the {server} MCP server",
                )

    indexes = {
        "codegraph": {"present": (target / ".codegraph").is_dir()},
        "serena": {"present": (target / ".serena").is_dir()},
    }
    for name, index in indexes.items():
        if not index["present"]:
            add_issue(
                issues,
                f"index_{name}_missing",
                f"target repository has no .{name} directory",
            )

    if command_paths["codegraph"]:
        codegraph_status = inspect_codegraph(
            command_paths["codegraph"], target, issues
        )
    else:
        codegraph_status = unknown_codegraph_status()

    return {
        "targetRepo": str(target),
        "commands": commands,
        "sharedConfig": config,
        "indexes": indexes,
        "codegraphStatus": codegraph_status,
        "issues": issues,
        "ok": not issues,
    }


def format_pending(status: dict[str, Any]) -> str:
    count = status["pendingChangeCount"]
    pending = status["pendingChanges"]
    if count is None or not isinstance(pending, dict):
        return "UNKNOWN"
    details = ", ".join(f"{key}={pending[key]}" for key in PENDING_CHANGE_KEYS)
    return f"{count} ({details})"


def print_human(report: dict[str, Any]) -> None:
    print("# Code Intel Doctor")
    print(f"Target repo: {report['targetRepo']}")
    print("\n## Commands")
    for name, command in report["commands"].items():
        path = command["path"]
        print(f"- {name}: {mark(command['available'])}{' ' + path if path else ''}")

    print("\n## Shared config")
    labels = {
        "sourceCodex": "configs/codex config",
        "sourceClaude": "configs/mcp.json",
        "liveCodex": "live ~/.codex/config.toml",
    }
    for server in ("codegraph", "serena"):
        for location, label in labels.items():
            present = report["sharedConfig"][location][server]
            print(f"- {label} has {server}: {mark(present)}")

    print("\n## Target repo indexes")
    print(
        f"- .codegraph directory: {mark(report['indexes']['codegraph']['present'])}"
    )
    print(f"- .serena directory: {mark(report['indexes']['serena']['present'])}")

    status = report["codegraphStatus"]
    print("\n## Codegraph status")
    if not status["checked"]:
        print("- status: NOT CHECKED (codegraph command unavailable)")
    elif not status["commandOk"]:
        print(f"- status: ERROR ({status['error']})")
    else:
        reindex = status["reindexRecommended"]
        reindex_label = "UNKNOWN" if reindex is None else "YES" if reindex else "NO"
        print(f"- reindexRecommended: {reindex_label}")
        print(f"- pendingChanges: {format_pending(status)}")
        if not status["worktreeMismatchKnown"]:
            mismatch_label = "UNKNOWN"
        elif status["worktreeMismatch"] is None or status["worktreeMismatch"] is False:
            mismatch_label = "NONE"
        else:
            mismatch_label = "DETECTED"
        print(f"- worktreeMismatch: {mismatch_label}")

    print("\n## Findings")
    if report["issues"]:
        for issue in report["issues"]:
            print(f"- [{issue['code']}] {issue['message']}")
    else:
        print("- No issues found.")

    print("\n## Next actions")
    issue_codes = {issue["code"] for issue in report["issues"]}
    if "index_codegraph_missing" in issue_codes:
        print(
            "- Run `codegraph init -i` in the target repo when graph "
            "tracing is needed."
        )
    if "index_serena_missing" in issue_codes:
        print("- Activate the repo with serena once before relying on LSP edits.")
    if issue_codes & {
        "codegraph_reindex_recommended",
        "codegraph_pending_changes",
        "codegraph_worktree_mismatch",
    }:
        print(
            "- Refresh the codegraph index and verify "
            "`codegraph status --json` is clean."
        )
    print(
        "- Re-run this doctor after setup and prefer codegraph for broad traces, "
        "serena for type-aware edits."
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    target = resolve_target(parser, args.repo)
    report = build_report(target)

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)

    return 1 if args.strict and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
