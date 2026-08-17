from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).parent


def _load(name: str):
    """Reuse an already-loaded module.

    Without the cache, mutual imports turn into infinite recursion. It actually
    hung on the structure where compiler calls queries and queries calls compiler.
    """
    key = f"llmwiki_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


frontmatter = _load("frontmatter")


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_page(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, ""
    return frontmatter.parse(path.read_text(encoding="utf-8"))


def write_page(path: Path, meta: dict, body: str) -> bool:
    """Write only when the content changed, so Obsidian sees no pointless edits."""
    text = frontmatter.render(meta, body)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    write_atomic(path, text)
    return True


def append_log(vault: Path, kind: str, detail: str) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    line = f"## [{date.today().isoformat()}] {kind} | {detail}\n"
    fd = os.open(vault / "log.md", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
