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


vaultio = _load("vaultio")

TASKS_BASE = """filters:
  and:
    - type == "task"
formulas:
  daysSinceModified: '((number(now()) - number(file.mtime)) / 86400000).floor()'
properties:
  note.id:
    displayName: ID
  note.title:
    displayName: 제목
views:
  - type: table
    name: 진행 중
    filters: 'status == "doing"'
    order: [id, title, project, last_active, last_harness]
    sort:
      - property: last_active
        direction: DESC
  - type: table
    name: 정체 경고
    filters: 'status == "doing" && formula.daysSinceModified > 7'
    order: [id, title, project, last_active]
    sort:
      - property: last_active
        direction: ASC
  - type: table
    name: 대기 큐
    filters: 'status == "queued"'
    order: [id, title, project, priority, created]
    sort:
      - property: priority
        direction: ASC
"""

# 차단 목록은 첫 compile 전에 있어야 한다. 실제 데이터에서 이 넷이 페이지를
# 만들었다: yongjae(홈 디렉터리), Documents, workspace, tmp.
CONFIG_SEED = """# llmwiki 설정. 스펙 5.4 참조.
#
# 백업은 두 곳이다. 볼트가 파생물이라는 말은 절반만 맞다.
#   ~/.local/share/llmwiki  events.ndjson, state.json, bindings.ndjson, 이 파일
#   볼트                     GEN 마커 밖에 직접 쓴 글, tasks/ 의 태스크 페이지
# GEN 영역은 events 에서 다시 만들어지지만 나머지는 볼트에만 있다.

# 볼트(생성된 페이지)가 놓일 곳. 비우면 ~/Documents/llmwiki.
# 여기서 정해야 CLI, 훅, launchd 가 같은 답을 본다 - 셸 환경변수로 바꾸면
# 훅과 야간 작업이 그것을 보지 못해 볼트가 둘로 갈라진다.
vault = ""

# 프로젝트 페이지를 만들지 않을 이름. 버리는 것이 아니라 unfiled 로 모은다.
# claude-mem 이 세션 cwd 의 마지막 이름을 프로젝트로 쓰기 때문에, 프로젝트
# 폴더 밖에서 시작한 세션은 부모 폴더 이름을 달고 온다.
blocklist = ["yongjae", "Documents", "workspace", "tmp", "probe-0000"]

active_threshold = 5
unclassified_days = 14
index_max_chars = 8000
archive_days = 180
stale_days = 7

[mapping]
# 워크트리 디렉터리를 본체 slug 로 합친다.
"ui-skills/2026-06-22" = "ui-skills"
"ui-skills/2026-06-27-adcker4" = "ui-skills"
"ui-skills/2026-06-27-adcker5" = "ui-skills"
"ui-skills/2026-06-27-fourmula2" = "ui-skills"
"ui-skills/ui-skills-validation" = "ui-skills"
"""

DASHBOARD = """# 대시보드

![[tasks.base]]

<!-- GEN:activity -->
_아직 compile 되지 않음_
<!-- /GEN:activity -->
"""


def init(vault: Path, home: Path, force: bool = False) -> dict:
    if vault.exists() and any(vault.iterdir()) and not force:
        raise FileExistsError(f"{vault} 가 비어 있지 않다. --force 로 덮어쓸 수 있다")
    for folder in ("tasks", "projects", "bases", "raw", "library"):
        (vault / folder).mkdir(parents=True, exist_ok=True)
    created = []
    for rel, text in (
        ("index.md", "# index\n"),
        ("log.md", ""),
        ("dashboard.md", DASHBOARD),
        ("bases/tasks.base", TASKS_BASE),
    ):
        target = vault / rel
        if target.exists():
            continue
        vaultio.write_atomic(target, text)
        created.append(rel)
    home.mkdir(parents=True, exist_ok=True)
    if not (home / "config.toml").exists():
        vaultio.write_atomic(home / "config.toml", CONFIG_SEED)
        created.append("config.toml")
    return {"created": created}
