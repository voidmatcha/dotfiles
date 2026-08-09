from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).parent


def _load(name: str):
    """이미 로드된 모듈은 재사용한다.

    캐시하지 않으면 상호 참조가 무한 재귀가 된다. compiler 가 queries 를,
    queries 가 compiler 를 부르는 구조에서 실제로 멈췄다.
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


def _strict_ok(text: str) -> bool:
    """PyYAML이 있으면 엄격 파서로 한 번 더 통과시킨다. 없으면 검사를 건너뛴다.

    관대한 파서는 'description: foo: bar' 를 통과시키지만 Obsidian 은 깨진다.
    하드 의존을 만들지 않으려 import 실패는 조용히 통과시킨다.
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
