from __future__ import annotations

import importlib.util
import sys
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


markers, frontmatter, store = _load("markers"), _load("frontmatter"), _load("store")

TASK_REQUIRED = ("type", "id", "project", "status")
PROJECT_REQUIRED = ("type", "slug", "status")
INDEX_EXEMPT = ("done", "archived")

# Hand-editable pages that live outside tasks/ and projects/ but that compile
# still writes into through GEN markers. Nothing checked them, so damage here
# surfaced only as a traceback from the middle of a compile run.
#
# A warning, not an error, on purpose. An error stops compile (see __main__),
# and the nightly job chains compile with the snapshot - blocking the run to
# protect a table that only gets rebuilt from events would cost the one backup
# of the prose that exists nowhere else. compile skips the damaged section and
# keeps going; this line is what makes the skip visible.
LOOSE_PAGES = ("dashboard.md",)


def _strict_ok(text: str) -> bool:
    """Run it through a strict parser too if PyYAML is present; skip if it is not.

    The lenient parser accepts 'description: foo: bar', but Obsidian breaks on it.
    To avoid a hard dependency, an import failure passes silently.
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return True
    if not text.startswith("---\n"):
        return True
    block, _, _ = text[4:].partition("\n---")
    try:
        yaml.safe_load(block)
    except Exception:
        return False
    return True


def run(home: Path, vault: Path, cfg) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    index_path = vault / "index.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    task_ids: set[str] = set()
    slugs: list[str] = []

    for folder, required in (("tasks", TASK_REQUIRED), ("projects", PROJECT_REQUIRED)):
        base = vault / folder
        for page in sorted(base.glob("*.md")) if base.exists() else []:
            text = page.read_text(encoding="utf-8")
            rel = f"{folder}/{page.name}"
            for problem in markers.validate(text):
                errors.append(f"{rel}: {problem}")
            if not _strict_ok(text):
                errors.append(f"{rel}: 프론트매터가 엄격 파서를 통과하지 못함")
            meta, _ = frontmatter.parse(text)
            for key in required:
                if key not in meta:
                    errors.append(f"{rel}: 필수 키 '{key}' 누락")
            if meta.get("status") == "blocked" and not str(meta.get("blocked_by", "")).strip():
                errors.append(f"{rel}: status=blocked 인데 blocked_by 가 비어 있음")
            if folder == "tasks" and "id" in meta:
                task_ids.add(str(meta["id"]))
            if folder == "projects" and "slug" in meta:
                slugs.append(str(meta["slug"]))
            if meta.get("status") not in INDEX_EXEMPT and rel not in index_text:
                warnings.append(f"{rel}: index.md 에 없는 고아 페이지")

    for name in LOOSE_PAGES:
        page = vault / name
        if not page.is_file():
            continue
        for problem in markers.validate(page.read_text(encoding="utf-8", errors="replace")):
            warnings.append(f"{name}: {problem} — compile 이 이 구역을 건너뛴다")

    duplicates = {s for s in slugs if slugs.count(s) > 1}
    errors.extend(f"slug 중복: {s}" for s in sorted(duplicates))

    if len(index_text) > cfg.index_max_chars:
        warnings.append(f"index.md 가 {cfg.index_max_chars}자를 초과함 ({len(index_text)}자)")

    events, broken = store.read_json(home / "events.ndjson")
    if broken:
        warnings.append(f"events.ndjson 에 깨진 줄 {broken}건")
    if not events:
        warnings.append("이벤트가 0건이다. 자동화가 멈췄을 수 있다")

    bindings, _ = store.read_json(home / "bindings.ndjson")
    for row in bindings:
        target = row.get("task_id")
        if target and target not in task_ids:
            warnings.append(f"존재하지 않는 태스크를 가리키는 바인딩: {target}")

    return errors, sorted(set(warnings))
