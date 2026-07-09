#!/usr/bin/env python3
"""Find imported agent assets with incomplete provenance metadata."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_REPO = Path(__file__).resolve().parents[1]
CANDIDATE_GLOBS = [
    "configs/agents/*.md",
    "configs/commands/*.md",
    "plugins/*/skills/*/SKILL.md",
    "plugins/*/.claude-plugin/plugin.json",
    "plugins/*/.codex-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
]
PROVENANCE_HINT_RE = re.compile(
    r"(?im)(^\s*provenance:|^\s*(?:source|upstream):|dotfiles\.provenance\.upstream)"
)
VALID_MODES = {"vendored", "adapted", "inspired-by", "original"}


def capture(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip().strip('"\'').rstrip(".;")
    return ""


def provenance_fields(text: str) -> dict[str, str]:
    fields = {
        "upstream": capture(
            text,
            [
                r"^\s+dotfiles\.provenance\.upstream:\s*(.+?)\s*$",
                r"\bUpstream:\s*([^;\n]+)",
                r"\bSource:\s*([^;\n]+)",
            ],
        ),
        "license": capture(text, [r"^license:\s*(.+?)\s*$", r"\bLicense:\s*([^;\n]+)"]),
        "mode": capture(
            text,
            [
                r"^\s+dotfiles\.provenance\.mode:\s*(.+?)\s*$",
                r"\bMode:\s*(vendored|adapted|inspired[- ]by|original)\b",
            ],
        ).lower().replace(" ", "-"),
        "local_changes": capture(
            text,
            [
                r"^\s+dotfiles\.provenance\.local-changes:\s*(.+?)\s*$",
                r"\bLocal changes:\s*([^;\n]+)",
            ],
        ),
    }
    return fields


def audit(root: Path) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = []
    scanned = 0
    seen: set[Path] = set()
    for glob in CANDIDATE_GLOBS:
        for path in sorted(root.glob(glob)):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            if not PROVENANCE_HINT_RE.search(text):
                continue
            fields = provenance_fields(text)
            missing: list[str] = []
            if not fields["mode"]:
                missing.append("mode")
            elif fields["mode"] not in VALID_MODES:
                missing.append("valid_mode")
            elif fields["mode"] != "original":
                missing.extend(name for name in ("upstream", "license") if not fields[name])
            if fields["mode"] == "adapted" and not fields["local_changes"]:
                missing.append("local_changes")
            if missing:
                gaps.append(
                    {
                        "path": str(path.relative_to(root)),
                        "missing": missing,
                        "mode": fields["mode"] or None,
                    }
                )
    return {"root": str(root), "scanned": scanned, "gaps": gaps}


def render_text(report: dict[str, Any]) -> str:
    lines = ["# Source Provenance Audit", f"Scanned: {report['scanned']} asset file(s)"]
    if not report["gaps"]:
        lines.append("No likely provenance gaps found by heuristic scan.")
    else:
        lines.append("Likely needs provenance metadata:")
        for gap in report["gaps"]:
            lines.append(f"- {gap['path']}: missing {', '.join(gap['missing'])}")
        lines.append("\nAdd Upstream, License, Mode, and Local changes for adapted assets.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_REPO), help="repository root to audit")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--strict", action="store_true", help="exit nonzero when provenance gaps exist")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"repository root is not a directory: {root}")
    report = audit(root)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 1 if args.strict and report["gaps"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
