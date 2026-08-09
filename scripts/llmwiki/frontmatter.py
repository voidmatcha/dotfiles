from __future__ import annotations

import re

_DELIM = "---"
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?)?$")
_UNSAFE_LEAD = tuple("-?>|&*!%@`{}[],#\"'")


def parse(text: str) -> tuple[dict, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != _DELIM:
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _DELIM)
    except StopIteration:
        return {}, text
    meta: dict = {}
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, raw = stripped.partition(":")
        meta[key.strip()] = _coerce(raw.strip())
    return meta, "\n".join(lines[end + 1 :])


def _coerce(raw: str):
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_unquote(p.strip()) for p in inner.split(",")]
    value = _unquote(raw)
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def quote(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(quote(v) for v in value) + "]"
    text = "" if value is None else str(value)
    if text == "":
        return '""'
    if _ISO.match(text):
        return text
    risky = (
        text.startswith(_UNSAFE_LEAD)
        or ": " in text
        or " #" in text
        or text.endswith(":")
        or "\n" in text
    )
    if risky:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def render(meta: dict, body: str) -> str:
    """parse 의 정확한 역함수여야 한다.

    닫는 구분자 뒤의 개행이 없으면 두 번째 라운드트립에서 본문 첫 줄이
    구분자에 붙어 프론트매터 전체가 깨진다. parse 가 lines[end+1:] 를
    돌려주므로 render 는 반드시 '---\\n' 으로 끝내야 짝이 맞는다.
    """
    lines = [_DELIM]
    lines += [f"{key}: {quote(value)}" for key, value in meta.items()]
    lines.append(_DELIM)
    return "\n".join(lines) + "\n" + body


def merge(existing: dict, owned: dict, owner_keys: set[str]) -> dict:
    merged = dict(existing)
    for key, value in owned.items():
        if key in owner_keys:
            merged[key] = value
    return merged
