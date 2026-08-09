from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path


# 분류되지 않은 작업이 모이는 곳. 프로젝트가 아니라 대기실이다.
UNFILED = "unfiled"


def host() -> str:
    """이 머신의 안정적인 짧은 이름.

    event_id 네임스페이스로 쓴다. claude-mem 의 rowid 는 머신마다 1부터
    시작하므로, 호스트를 섞지 않으면 서로 다른 세션이 같은 event_id 를 갖고
    한쪽이 중복 제거로 조용히 사라진다.
    """
    raw = os.environ.get("LLMWIKI_HOST") or socket.gethostname().split(".")[0]
    return re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower() or "unknown"


def home() -> Path:
    return Path(os.environ.get("LLMWIKI_HOME", Path.home() / ".local/share/llmwiki"))


DEFAULT_VAULT = Path.home() / "Documents/llmwiki"


def vault(home_dir: Path | None = None) -> Path:
    """볼트 경로. env > config.toml > 기본값.

    home() 은 부트스트랩 지점이라 env 로만 정해진다 - config 를 찾으려면
    먼저 그 위치를 알아야 하니 달리 방법이 없다. 하지만 볼트는 그냥 설정값
    이므로 config.toml 에 둔다. 그래야 CLI, 훅, launchd 가 같은 답을 본다.

    env 만 있던 시절에는 갈라졌다. launchd 와 훅은 ~/.zshrc 를 읽지 않으므로
    LLMWIKI_VAULT 를 셸에 설정하면 손으로 친 명령만 새 경로를 쓰고 야간
    작업은 기본 경로에 계속 썼다. 볼트 두 개가 각자 자라고 아무도 알리지
    않는다. env 는 이제 일회성 실행과 테스트용으로만 남긴다.
    """
    raw = os.environ.get("LLMWIKI_VAULT")
    if raw:
        return _anchor(Path(raw).expanduser(), home_dir)
    if home_dir is not None:
        configured = load(home_dir).vault
        if configured:
            return _anchor(Path(configured).expanduser(), home_dir)
    return DEFAULT_VAULT


def _anchor(path: Path, home_dir: Path | None) -> Path:
    """상대경로를 config 가 있는 디렉터리에 붙인다.

    상대경로를 그대로 두면 프로세스의 cwd 에 따라 다른 볼트가 된다 -
    compile 은 체크아웃에서, doctor 는 사용자가 선 곳에서, 훅은 또 다른
    곳에서 돈다. 같은 설정이 서로 다른 절대경로로 풀리면 볼트가 갈라지고
    검사는 거짓 교체 경보를 낸다. home 은 어디서 실행하든 같으므로 그것을
    기준으로 삼는다.
    """
    if path.is_absolute() or home_dir is None:
        return path
    return home_dir / path


@dataclass(frozen=True)
class Config:
    blocklist: frozenset[str] = frozenset()
    mapping: dict[str, str] = field(default_factory=dict)
    active_threshold: int = 5
    unclassified_days: int = 14
    index_max_chars: int = 8000
    archive_days: int = 180
    stale_days: int = 7
    truncate_request: int = 120
    truncate_next: int = 200
    # 빈 문자열이면 "설정 안 함". Path 를 기본값으로 두면 config 없이 만든
    # Config() 가 이 머신의 홈 경로를 물고 다닌다.
    vault: str = ""

    def resolve_project(self, raw: str) -> str:
        """매핑을 먼저 적용하고 그 결과를 차단 목록에 대본다.

        차단은 페이지를 막을 뿐 기록을 지우지 않는다. claude-mem 은 세션
        cwd 의 마지막 이름을 프로젝트로 쓰기 때문에, 프로젝트 폴더 밖에서
        세션을 시작하면 'Documents' 나 'yongjae' 같은 이름이 붙는다. 그것은
        잡동사니라는 뜻이 아니라 시작 위치가 얕았다는 뜻이다 - 실제로 그
        이름들 아래에 작업 235건이 있었다. 차단된 것은 UNFILED 로 모으고,
        어디서 왔는지는 origin 으로 남겨 나중에 mapping 으로 되돌릴 수 있게
        한다.
        """
        slug = self.mapping.get(raw, raw)
        return UNFILED if slug in self.blocklist else slug


def load(home_dir: Path) -> Config:
    path = home_dir / "config.toml"
    data: dict = {}
    if path.exists():
        # tomllib 은 3.11+ 에만 있다. 모듈을 불러오는 것만으로 그 의존을 지면
        # 그 파이썬에서는 llmwiki 를 import 하는 모든 테스트가 함께 죽는다.
        # 실제로 tomllib 을 막고 verify.sh 를 돌리는 테스트에서 단위 테스트
        # 21개가 무너졌다. 설정을 읽을 때만 필요하므로 여기서 불러온다.
        try:
            import tomllib
        except ModuleNotFoundError as exc:  # pragma: no cover - 3.11+ 에서는 안 온다
            raise RuntimeError(
                f"{path} 를 읽으려면 tomllib(파이썬 3.11+)이 필요하다. "
                "설정을 조용히 무시하면 blocklist 와 mapping 이 사라져 "
                "compile 이 잘못된 프로젝트 페이지를 만든다."
            ) from exc
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    defaults = Config()
    return Config(
        blocklist=frozenset(data.get("blocklist", [])),
        mapping=dict(data.get("mapping", {})),
        active_threshold=int(data.get("active_threshold", defaults.active_threshold)),
        unclassified_days=int(data.get("unclassified_days", defaults.unclassified_days)),
        index_max_chars=int(data.get("index_max_chars", defaults.index_max_chars)),
        archive_days=int(data.get("archive_days", defaults.archive_days)),
        stale_days=int(data.get("stale_days", defaults.stale_days)),
        truncate_request=int(data.get("truncate_request", defaults.truncate_request)),
        truncate_next=int(data.get("truncate_next", defaults.truncate_next)),
        vault=str(data.get("vault", defaults.vault)),
    )
