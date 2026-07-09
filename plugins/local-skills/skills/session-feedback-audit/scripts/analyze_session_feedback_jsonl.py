#!/usr/bin/env python3
"""Analyze local JSONL sessions for repeated user corrections and requests."""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

AGENTS_NOISE_RE = re.compile(r"AGENTS\.md|AUTONOMOUS CODING AGENT|<INSTRUCTIONS>|Session:", re.I)
UNICODE_WORD_RE = re.compile(r"(?u)\b[\w.:-]{2,}\b")
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")
PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?P<label>(?:(?:RSA|DSA|EC|OPENSSH|ENCRYPTED) )?PRIVATE KEY)-----"
    r".*?"
    r"-----END (?P=label)-----",
    re.IGNORECASE | re.DOTALL,
)
STANDALONE_CREDENTIAL_RE = re.compile(
    r"""(?x)
    (?<![A-Za-z0-9_-])
    (?:
        sk-(?:proj-)?[A-Za-z0-9_-]{20,} |
        gh[oprsu]_[A-Za-z0-9]{20,} |
        github_pat_[A-Za-z0-9_]{20,} |
        AKIA[0-9A-Z]{16} |
        eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{8,}
    )
    (?![A-Za-z0-9_-])
    """
)
COOKIE_HEADER_RE = re.compile(r"(?im)(\b(?:cookie|set-cookie)\s*[:=]\s*)[^\r\n]+")
QUERY_SECRET_RE = re.compile(
    r"(?i)([?&][a-z0-9_.-]*(?:token|secret|password|passwd|auth|signature|api[_-]?key)[a-z0-9_.-]*=)[^&#\s]+"
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?P<prefix>
        (?<![\w-])
        ["']?
        (?:[a-z0-9][a-z0-9_.-]*[_\-.])?
        (?:
            secret[_-]?access[_-]?key|access[_-]?key(?:[_-]?id)?|
            access[_-]?token|refresh[_-]?token|id[_-]?token|token|
            api[_-]?key|client[_-]?secret|secret[_-]?key|private[_-]?key|
            database[_-]?url|secret|password|passwd|
            authorization|cookie|set-cookie|session(?:id)?|csrf(?:token)?
        )
        ["']?
        \s*[:=]\s*
    )
    (?P<value>
        bearer\s+[^\s,;]+|
        "(?:\\.|[^"\\])*"|
        '(?:\\.|[^'\\])*'|
        [^\r\n,;&}\]]+
    )
    """
)

BUILTIN_PATTERN_PACKS: dict[str, dict[str, list[str]]] = {
    "ko": {
        "scope_correction": ["아니", "그게 아니라", "내 말은", "말한거임", "이거말고", "이거 말고", "그거말고", "그거 말고", "롤백"],
        "direct_action": ["해줘", "줘", "ㄱㄱ", "켜", "띄워", "깔", "설치", "실행", "풀", "푸시", "스테이지", "추가"],
        "repo_boundary": ["저장소", "브랜치", "워크트리", "worktree", "작업 폴더", "작업 디렉터리"],
        "artifact_link": ["링크", "html", "스크린샷", "보고서", "경로", "산출물"],
        "runtime_environment": ["실행 환경", "로컬 환경", "개발 환경", "테스트 환경", "스테이징", "프로덕션", "운영 환경", "배포 환경", "컨테이너", "가상머신", "기기", "시뮬레이터"],
        "language_polish": ["한국어", "영어", "윤문", "다국어", "언어", "번역", "용어", "표기"],
        "avoid_confirmation": ["그냥", "알아서", "바로", "반복", "매번", "묻지", "옵션"],
    },
    "en": {
        "scope_correction": ["not what i meant", "that is not", "that's not", "i mean", "not this", "instead", "roll back", "revert"],
        "direct_action": ["do it", "run it", "execute", "install", "pull", "push", "stage", "open it", "start it", "fix it", "apply it"],
        "repo_boundary": ["repository", "repo", "branch", "worktree", "cwd", "remote"],
        "artifact_link": ["link", "html", "screenshot", "report", "path", "artifact"],
        "runtime_environment": ["runtime environment", "local environment", "development environment", "test environment", "staging", "production", "deployed environment", "container", "virtual machine", "device", "simulator"],
        "language_polish": ["english", "korean", "translation", "wording", "copy", "language", "terminology", "literal translation", "polish"],
        "avoid_confirmation": ["just", "do not ask", "don't ask", "stop asking", "without asking", "proceed", "go ahead", "automatically"],
    },
}


class InputSelectionError(ValueError):
    """Raised when an explicit input cannot be treated as JSONL evidence."""

RULE_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "scope_correction": "When the user corrects the scope, discard the superseded assumption and restate the latest target before continuing.",
        "direct_action": "When the user uses an execution verb, perform the safe requested action and report verification evidence before adding explanation.",
        "repo_boundary": "When similar repositories are in play, verify cwd, git status, and remote before editing, and never mix changes across repositories.",
        "artifact_link": "For links, reports, screenshots, or other artifacts, provide the concrete path or URL and keep temporary evidence untracked unless requested.",
        "runtime_environment": "Distinguish local, test or staging, and production results; record the runtime environment, version or commit, and execution target with the evidence.",
        "language_polish": "Separate identifiers and source text from edited copy, preserve canonical technical names, and polish only the requested language surface.",
        "avoid_confirmation": "Proceed with clear, reversible local work without permission handoffs; ask only for destructive, credential-gated, or production actions.",
    },
    "ko": {
        "scope_correction": "사용자가 범위를 정정하면 폐기된 가정을 버리고 최신 목표를 다시 고정한 뒤 계속한다.",
        "direct_action": "사용자가 실행 동사를 쓰면 안전한 요청을 실제로 수행하고 설명보다 검증 근거를 먼저 제공한다.",
        "repo_boundary": "비슷한 저장소가 여러 개면 작업 전에 cwd·git status·remote를 확인하고 저장소 간 변경을 섞지 않는다.",
        "artifact_link": "링크·보고서·스크린샷·산출물 요청에는 실제 경로나 URL을 제공하고, 임시 증거는 요청 전까지 추적하지 않는다.",
        "runtime_environment": "로컬·테스트 또는 스테이징·프로덕션 결과를 구분하고 실행 환경·버전 또는 commit·실행 대상을 근거와 함께 기록한다.",
        "language_polish": "식별자와 원문을 수정할 문구와 분리하고 canonical 기술 명칭을 보존하며 요청된 언어 표면만 윤문한다.",
        "avoid_confirmation": "명확하고 되돌릴 수 있는 로컬 작업은 확인 질문 없이 진행하고 파괴적·credential·production 작업만 묻는다.",
    },
}


def parse_duration(value: str) -> dt.timedelta:
    m = re.fullmatch(r"(\d+)([dhm])", value.strip())
    if not m:
        raise argparse.ArgumentTypeError("duration must look like 7d, 24h, or 30m")
    n = int(m.group(1))
    unit = m.group(2)
    return {"d": dt.timedelta(days=n), "h": dt.timedelta(hours=n), "m": dt.timedelta(minutes=n)}[unit]


def iter_paths(inputs: list[str], recent: Optional[str]) -> list[Path]:
    paths: list[Path] = []
    if inputs:
        for item in inputs:
            expanded = os.path.expanduser(item)
            matches = glob.glob(expanded)
            if not matches:
                raise InputSelectionError(f"missing input or unmatched glob: {item}")
            for match in matches:
                p = Path(match)
                if p.is_dir():
                    discovered = sorted(candidate for candidate in p.rglob("*.jsonl") if candidate.is_file())
                    if not discovered:
                        raise InputSelectionError(f"input directory contains no JSONL files: {p}")
                    paths.extend(discovered)
                elif p.is_file():
                    if p.suffix.lower() != ".jsonl":
                        raise InputSelectionError(f"input file must use the .jsonl extension: {p}")
                    paths.append(p)
                else:
                    raise InputSelectionError(f"invalid or unreadable input path: {p}")
    else:
        base = Path.home() / ".codex" / "sessions"
        paths = sorted(base.rglob("*.jsonl")) if base.exists() else []

    if recent:
        cutoff = dt.datetime.now().timestamp() - parse_duration(recent).total_seconds()
        filtered: list[Path] = []
        for path in paths:
            try:
                if path.stat().st_mtime >= cutoff:
                    filtered.append(path)
            except OSError as exc:
                if inputs:
                    raise InputSelectionError(f"cannot stat input {path}: {exc}") from exc
        paths = filtered

    # newest first, but stable unique
    seen: set[Path] = set()
    unique: list[Path] = []
    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return float("-inf")

    for p in sorted(paths, key=mtime, reverse=True):
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(rp)
    return unique


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("input_text") or item.get("output_text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if isinstance(content, dict):
        for key in ("text", "input_text", "output_text"):
            if isinstance(content.get(key), str):
                return content[key]
    return ""


def extract_message(obj: dict[str, Any]) -> Optional[tuple[str, str]]:
    if not isinstance(obj, dict):
        return None

    message = obj.get("message")
    if obj.get("type") in {"user", "assistant"} and isinstance(message, dict):
        role = message.get("role")
        if role in {"user", "assistant"}:
            return str(role), text_from_content(message.get("content"))

    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
    if not isinstance(payload, dict):
        return None
    if payload.get("type") == "message" and payload.get("role") in {"user", "assistant"}:
        return str(payload["role"]), text_from_content(payload.get("content"))
    if obj.get("type") in {"user_message", "assistant_message"}:
        role = "user" if obj.get("type") == "user_message" else "assistant"
        return role, text_from_content(payload.get("content") or payload.get("text"))
    return None


def redact_sensitive(text: str) -> str:
    """Remove common credential and identity material before any derivation."""

    redacted = PEM_PRIVATE_KEY_RE.sub("<redacted>", text)
    redacted = COOKIE_HEADER_RE.sub(lambda match: match.group(1) + "<redacted-cookie>", redacted)
    redacted = QUERY_SECRET_RE.sub(lambda match: match.group(1) + "<redacted>", redacted)

    def redact_assignment(match: re.Match[str]) -> str:
        value = match.group("value")
        if value.startswith('"'):
            replacement = '"<redacted>"'
        elif value.startswith("'"):
            replacement = "'<redacted>'"
        else:
            replacement = "<redacted>"
        return match.group("prefix") + replacement

    redacted = SENSITIVE_ASSIGNMENT_RE.sub(redact_assignment, redacted)
    redacted = STANDALONE_CREDENTIAL_RE.sub("<redacted>", redacted)
    return EMAIL_RE.sub("<redacted-email>", redacted)


def clean_snippet(text: str, width: int = 160) -> str:
    text = redact_sensitive(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[: width - 1] + "…" if len(text) > width else text


def contains_pattern(text: str, pattern: str) -> bool:
    low = text.lower()
    normalized = pattern.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9 ._:'-]*", normalized):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", low))
    return normalized in low


def combined_patterns(extra_patterns: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = defaultdict(list)
    for pack in BUILTIN_PATTERN_PACKS.values():
        for category, patterns in pack.items():
            merged[category].extend(patterns)
    if extra_patterns:
        for category, patterns in extra_patterns.items():
            merged[category].extend(patterns)
    return dict(merged)


def load_pattern_pack(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("pattern pack must be a JSON object")
    patterns: dict[str, list[str]] = {}
    for category, values in data.items():
        if not isinstance(category, str) or not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("pattern pack values must be arrays of strings")
        patterns[category] = values
    return patterns


def matching_builtin_packs(text: str) -> list[str]:
    """Return pattern packs with an actual phrase match, not guessed languages."""

    matches: list[str] = []
    for pack_name, categories in BUILTIN_PATTERN_PACKS.items():
        if any(
            contains_pattern(text, pattern)
            for patterns in categories.values()
            for pattern in patterns
        ):
            matches.append(pack_name)
    return matches


def categorize(text: str, extra_patterns: dict[str, list[str]] | None = None) -> list[str]:
    low = text.lower()
    cats: list[str] = []
    for cat, pats in combined_patterns(extra_patterns).items():
        if any(contains_pattern(low, pattern) for pattern in pats):
            cats.append(cat)
    return cats


def is_noise_user_text(text: str) -> bool:
    return len(text) > 2500 and bool(AGENTS_NOISE_RE.search(text))


def analyze(
    paths: list[Path],
    limit_files: int,
    extra_patterns: dict[str, list[str]] | None = None,
    output_language: str = "auto",
    min_occurrences: int = 2,
    min_files: int = 2,
) -> dict[str, Any]:
    stats = Counter()
    cat_counts = Counter()
    pack_counts = Counter()
    category_files: dict[str, set[str]] = defaultdict(set)
    keyword_counts = Counter()
    snippets: dict[str, list[dict[str, str]]] = defaultdict(list)
    file_summaries: list[dict[str, Any]] = []

    for path in paths[:limit_files]:
        file_counts = Counter()
        display_path = redact_sensitive(str(path))
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            file_summaries.append({"path": display_path, "error": redact_sensitive(str(exc))})
            continue
        stats["readable_files"] += 1
        file_counts["readable"] = 1
        try:
            with handle:
                for lineno, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        stats["bad_json_lines"] += 1
                        file_counts["bad_json_lines"] += 1
                        continue
                    stats["valid_json_lines"] += 1
                    file_counts["valid_json_lines"] += 1
                    if not isinstance(obj, dict):
                        stats["non_object_json_lines"] += 1
                        file_counts["non_object_json_lines"] += 1
                        continue
                    stats["object_json_lines"] += 1
                    file_counts["object_json_lines"] += 1
                    msg = extract_message(obj)
                    if not msg:
                        continue
                    role, raw_text = msg
                    if role != "user":
                        continue
                    text = redact_sensitive(raw_text)
                    stats["user_messages"] += 1
                    file_counts["user_messages"] += 1
                    if is_noise_user_text(text):
                        stats["noise_user_messages"] += 1
                        continue
                    packs = matching_builtin_packs(text)
                    if packs:
                        stats["builtin_pack_messages"] += 1
                        file_counts["builtin_pack_messages"] += 1
                        for pack in packs:
                            pack_counts[pack] += 1
                            file_counts[f"{pack}_pack_messages"] += 1
                    else:
                        stats["unmatched_builtin_pack_messages"] += 1
                    cats = categorize(text, extra_patterns)
                    if not packs and not cats:
                        continue
                    if cats:
                        stats["flagged_messages"] += 1
                        file_counts["flagged_messages"] += 1
                    words = UNICODE_WORD_RE.findall(text)
                    for word in words:
                        if len(word) <= 1:
                            continue
                        if word.lower() in {"the", "and", "with", "this", "that", "redacted", "redacted-email", "redacted-cookie"}:
                            continue
                        keyword_counts[word] += 1
                    for cat in cats:
                        cat_counts[cat] += 1
                        category_files[cat].add(str(path))
                        if len(snippets[cat]) < 5:
                            snippets[cat].append({"path": display_path, "line": str(lineno), "text": clean_snippet(text)})
        except OSError as exc:
            file_summaries.append({"path": display_path, "error": redact_sensitive(str(exc)), **file_counts})
            stats["read_errors"] += 1
            continue
        file_summaries.append({"path": display_path, **file_counts})

    pattern_evidence = {
        category: {"occurrences": count, "files": len(category_files[category])}
        for category, count in cat_counts.most_common()
    }
    repeated_patterns = Counter(
        {
            category: count
            for category, count in cat_counts.items()
            if count >= min_occurrences and len(category_files[category]) >= min_files
        }
    )
    candidate_patterns = Counter(
        {category: count for category, count in cat_counts.items() if category not in repeated_patterns}
    )

    # Pattern-pack hits are evidence categories, not reliable language metadata.
    # Keep the default deterministic and require an explicit locale for Korean output.
    rule_language = "en" if output_language == "auto" else output_language
    templates = RULE_TEMPLATES[rule_language]
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stats": dict(stats),
        "matched_builtin_packs": dict(pack_counts.most_common()),
        "output_language": rule_language,
        "thresholds": {"min_occurrences": min_occurrences, "min_files": min_files},
        "categories": dict(cat_counts.most_common()),
        "pattern_evidence": pattern_evidence,
        "repeated_patterns": dict(repeated_patterns.most_common()),
        "candidate_patterns": dict(candidate_patterns.most_common()),
        "keywords": dict(keyword_counts.most_common(30)),
        "snippets": dict(snippets),
        "files": file_summaries,
        "rules": [templates[category] for category, _ in repeated_patterns.most_common() if category in templates],
    }


def render_markdown(result: dict[str, Any]) -> str:
    stats = Counter(result["stats"])
    lines: list[str] = []
    lines.append("# Session feedback audit")
    lines.append("")
    lines.append("## Summary")
    if result.get("generated_at"):
        lines.append(f"- Generated at: {result['generated_at']}")
    lines.append(f"- User messages scanned: {stats.get('user_messages', 0)}")
    lines.append(f"- User messages matching built-in pattern packs: {stats.get('builtin_pack_messages', 0)}")
    packs = result.get("matched_builtin_packs", {})
    if packs:
        lines.append("- Matched built-in packs: " + ", ".join(f"{name}={count}" for name, count in packs.items()))
    lines.append(f"- Flagged correction/re-request messages: {stats.get('flagged_messages', 0)}")
    lines.append(f"- Noise/bootstrap user messages skipped: {stats.get('noise_user_messages', 0)}")
    lines.append("")
    lines.append("## Repeated patterns")
    repeated_patterns = result.get("repeated_patterns", {})
    evidence = result.get("pattern_evidence", {})
    for cat, count in repeated_patterns.items():
        files = evidence.get(cat, {}).get("files", 0)
        occurrence_label = "occurrence" if count == 1 else "occurrences"
        file_label = "file" if files == 1 else "files"
        lines.append(f"- **{cat}**: {count} {occurrence_label} across {files} {file_label}")
    if not repeated_patterns:
        lines.append("- No repeated correction or re-request pattern detected in selected files.")
    lines.append("")
    lines.append("## Candidate patterns")
    candidate_patterns = result.get("candidate_patterns", {})
    for cat, count in candidate_patterns.items():
        files = evidence.get(cat, {}).get("files", 0)
        occurrence_label = "occurrence" if count == 1 else "occurrences"
        file_label = "file" if files == 1 else "files"
        lines.append(f"- **{cat}**: {count} {occurrence_label} across {files} {file_label}")
    if not candidate_patterns:
        lines.append("- None.")
    lines.append("")
    lines.append("## Polished anti-repeat rules")
    for i, rule in enumerate(result["rules"], 1):
        lines.append(f"{i}. {rule}")
    if not result["rules"]:
        thresholds = result.get("thresholds", {})
        lines.append(
            "- No durable rule generated; a pattern must meet both thresholds "
            f"({thresholds.get('min_occurrences', 2)} occurrences across "
            f"{thresholds.get('min_files', 2)} files)."
        )
    lines.append("")
    lines.append("## Evidence snippets")
    for cat, items in result["snippets"].items():
        lines.append(f"### {cat}")
        for item in items:
            lines.append(f"- `{item['path']}:{item['line']}` — {item['text']}")
        lines.append("")
    lines.append("## Frequent terms")
    if result["keywords"]:
        lines.append(", ".join(f"{k}({v})" for k, v in list(result["keywords"].items())[:30]))
    lines.append("")
    lines.append("## Files")
    for item in result["files"][:50]:
        path = item.get("path")
        if "error" in item:
            lines.append(f"- `{path}` error={item['error']}")
        else:
            lines.append(f"- `{path}` user={item.get('user_messages', 0)} matched_pack={item.get('builtin_pack_messages', 0)} flagged={item.get('flagged_messages', 0)}")
    return "\n".join(lines).rstrip() + "\n"


def atomic_write_private(path: Path, content: str) -> None:
    """Atomically replace path with a mode-0600 UTF-8 text file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        os.chmod(path, 0o600)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="JSONL files, dirs, or globs. Defaults to ~/.codex/sessions/**/*.jsonl")
    parser.add_argument("--recent", default=None, help="Filter by mtime, e.g. 7d, 24h, 120m")
    parser.add_argument("--limit-files", type=int, default=30)
    parser.add_argument("--patterns", help="Optional JSON pattern pack for another language or project vocabulary")
    parser.add_argument("--output-language", choices=["auto", "en", "ko"], default="auto", help="Language for generated rules")
    parser.add_argument("--min-occurrences", type=int, default=2, help="Minimum category occurrences required for a durable rule")
    parser.add_argument("--min-files", type=int, default=2, help="Minimum distinct JSONL files required for a durable rule")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--out", help="Write output to path instead of stdout")
    args = parser.parse_args(argv)

    if args.limit_files <= 0 or args.min_occurrences <= 0 or args.min_files <= 0:
        print("error: --limit-files, --min-occurrences, and --min-files must be greater than zero", file=sys.stderr)
        return 2

    try:
        paths = iter_paths(args.paths, args.recent)
        extra_patterns = load_pattern_pack(Path(os.path.expanduser(args.patterns))) if args.patterns else None
    except (InputSelectionError, argparse.ArgumentTypeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {redact_sensitive(str(exc))}", file=sys.stderr)
        return 2

    result = analyze(
        paths,
        args.limit_files,
        extra_patterns=extra_patterns,
        output_language=args.output_language,
        min_occurrences=args.min_occurrences,
        min_files=args.min_files,
    )
    stats = Counter(result["stats"])
    if paths and stats["readable_files"] == 0:
        print("error: all selected JSONL inputs were unreadable", file=sys.stderr)
        return 2
    if paths and stats["object_json_lines"] == 0:
        print("error: selected inputs contained no valid JSON object lines", file=sys.stderr)
        return 2

    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_markdown(result)
    if args.out:
        out = Path(os.path.expanduser(args.out))
        try:
            atomic_write_private(out, output)
        except OSError as exc:
            safe_out = redact_sensitive(str(out))
            print(f"error: cannot write output {safe_out}: {redact_sensitive(str(exc))}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
