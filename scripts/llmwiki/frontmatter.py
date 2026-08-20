from __future__ import annotations

import re

_DELIM = "---"
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?)?$")
_UNSAFE_LEAD = tuple("-?>|&*!%@`{}[],#\"'")

# quote() encodes with the first table, _unquote() decodes with the second.
# They must stay exact inverses: while _unquote never unescaped, every rewrite
# doubled the backslashes of a quoted title until the value was unreadable.
_ESCAPE = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_UNESCAPE = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}

# Synthetic key for frontmatter lines that belong to no key at all - comments,
# blank lines, stray continuation lines. NUL cannot occur in a real YAML key,
# so these never collide with the user's own keys.
_ORPHAN_KEY = "\x00raw"


class RawValue(str):
    """A frontmatter entry carried through as its original source lines.

    A flat dict cannot represent every YAML shape - block sequences, nested
    maps, multi-line scalars - and pushing such an entry back through the
    scalar parser destroys hand-written data. Obsidian's native block style

        tags:
          - wiki
          - personal

    used to parse to an empty string and get rewritten as ``tags: ""``. The
    compiler owns only its own keys, so anything the scalar parser cannot
    round-trip is kept verbatim and rendered back byte-for-byte instead.

    The str value is the value text, so ``meta.get(key)`` still returns
    something readable; ``source`` is what render() writes back.
    """

    def __new__(cls, value: str, source: str) -> RawValue:
        obj = super().__new__(cls, value)
        obj.source = source
        return obj


def parse(text: str) -> tuple[dict, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != _DELIM:
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _DELIM)
    except StopIteration:
        return {}, text
    return _parse_block(lines[1:end]), "\n".join(lines[end + 1 :])


def _is_continuation(line: str) -> bool:
    """True when the line belongs to the entry above instead of opening a key.

    Both indented children and the unindented ``- item`` sequence style that
    Obsidian writes have to count, or the list is torn off its key.
    """
    if line[:1] in (" ", "\t"):
        return True
    return line.lstrip().startswith("- ") or line.strip() == "-"


def _parse_block(block: list[str]) -> dict:
    meta: dict = {}
    orphans: list[str] = []

    def flush() -> None:
        """Park comments and blanks under a synthetic key so render keeps them."""
        nonlocal orphans
        if orphans:
            meta[f"{_ORPHAN_KEY}{len(meta)}"] = RawValue("", "\n".join(orphans))
            orphans = []

    index = 0
    while index < len(block):
        line = block[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped \
                or _is_continuation(line):
            orphans.append(line)
            index += 1
            continue

        end = index + 1
        while end < len(block) and _is_continuation(block[end]):
            end += 1
        tail = block[index + 1 : end]
        key, _, inline = line.partition(":")
        flush()
        if tail or not inline.strip():
            # Block sequence, nested map, multi-line scalar or explicit null:
            # out of the scalar parser's reach, so keep the source rather than
            # guess at it and lose the user's data.
            meta[key.strip()] = RawValue(
                "\n".join([inline] + tail).strip(), "\n".join([line] + tail)
            )
        else:
            meta[key.strip()] = _coerce(inline.strip())
        index = end
    flush()
    return meta


def _coerce(raw: str):
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_unquote(part) for part in _split_flow(inner)]
    value = _unquote(raw)
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _split_flow(inner: str) -> list[str]:
    """Split a flow sequence on commas that are not inside a quoted scalar.

    A naive split tears '["a, b"]' in half, which would make quote() and parse()
    stop being inverses for any list item holding a comma.
    """
    parts: list[str] = []
    buf: list[str] = []
    closer = ""
    escaped = False
    for char in inner:
        if escaped:
            buf.append(char)
            escaped = False
        elif closer == '"' and char == "\\":
            buf.append(char)
            escaped = True
        elif closer:
            buf.append(char)
            if char == closer:
                closer = ""
        elif char in "\"'":
            buf.append(char)
            closer = char
        elif char == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf).strip())
    return parts


def _decode_double(raw: str) -> str | None:
    """Decode a fully double-quoted scalar, or None if raw is not exactly one."""
    out: list[str] = []
    index = 1
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            following = raw[index + 1]
            # An escape quote() never emits stays verbatim, so a hand-written
            # "C:\path" keeps its backslash instead of quietly losing it.
            out.append(_UNESCAPE.get(following, "\\" + following))
            index += 2
            continue
        if char == '"':
            return "".join(out) if index == len(raw) - 1 else None
        out.append(char)
        index += 1
    return None


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == '"':
        decoded = _decode_double(raw)
        if decoded is not None:
            return decoded
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'" \
            and "'" not in raw[1:-1].replace("''", ""):
        return raw[1:-1].replace("''", "'")
    return raw


def quote(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_quote_item(v) for v in value) + "]"
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
        # parse() strips each value, and a bare control character would either
        # break the one-line shape or come back trimmed - both lose the value.
        or text != text.strip()
        or any(char in text for char in "\n\r\t")
    )
    if risky:
        return '"' + "".join(_ESCAPE.get(char, char) for char in text) + '"'
    return text


def _quote_item(value) -> str:
    """Quote a flow-sequence item.

    An item is safe on its own line but not inside '[...]': a bare comma or
    bracket would be read back as a sequence separator and split the item.
    """
    text = quote(value)
    if isinstance(value, str) and not text.startswith('"') \
            and any(char in text for char in ",[]"):
        return '"' + "".join(_ESCAPE.get(char, char) for char in text) + '"'
    return text


def render(meta: dict, body: str) -> str:
    """Must be the exact inverse of parse.

    Without the newline after the closing delimiter, the second round trip glues
    the body's first line onto the delimiter and the whole frontmatter breaks.
    parse returns lines[end+1:], so render must end with '---\\n' to match.
    """
    lines = [_DELIM]
    for key, value in meta.items():
        if isinstance(value, RawValue):
            lines.extend(value.source.split("\n"))
        else:
            lines.append(f"{key}: {quote(value)}")
    lines.append(_DELIM)
    return "\n".join(lines) + "\n" + body


def merge(existing: dict, owned: dict, owner_keys: set[str]) -> dict:
    merged = dict(existing)
    for key, value in owned.items():
        if key in owner_keys:
            merged[key] = value
    return merged
