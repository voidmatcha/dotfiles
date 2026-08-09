from __future__ import annotations

import re

OPEN = re.compile(r"^<!-- GEN:([a-z0-9-]+) -->$", re.MULTILINE)
CLOSE = re.compile(r"^<!-- /GEN:([a-z0-9-]+) -->$", re.MULTILINE)


def _tokens(text: str) -> list[tuple[str, str, int]]:
    found = [("open", m.group(1), m.start()) for m in OPEN.finditer(text)]
    found += [("close", m.group(1), m.start()) for m in CLOSE.finditer(text)]
    return sorted(found, key=lambda t: t[2])


def validate(text: str) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    stack: list[str] = []
    for kind, name, _ in _tokens(text):
        if kind == "open":
            if stack:
                errors.append(f"GEN:{name} 이 GEN:{stack[-1]} 안에 중첩됨")
            if name in seen:
                errors.append(f"GEN:{name} 이 중복 정의됨")
            seen.add(name)
            stack.append(name)
        else:
            if not stack:
                errors.append(f"/GEN:{name} 에 대응하는 여는 마커 없음")
            elif stack[-1] != name:
                errors.append(f"GEN:{stack[-1]} 이 /GEN:{name} 으로 닫힘")
                stack.pop()
            else:
                stack.pop()
    errors.extend(f"GEN:{name} 이 닫히지 않음" for name in stack)
    return errors


def replace(text: str, name: str, body: str) -> str:
    errors = validate(text)
    if errors:
        raise ValueError("; ".join(errors))
    open_tag, close_tag = f"<!-- GEN:{name} -->", f"<!-- /GEN:{name} -->"
    block = f"{open_tag}\n{body.rstrip()}\n{close_tag}"
    pattern = re.compile(
        rf"^{re.escape(open_tag)}$.*?^{re.escape(close_tag)}$",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    prefix = text if text.endswith("\n") else text + "\n"
    return f"{prefix}\n{block}\n"
