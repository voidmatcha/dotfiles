from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path


# Where unclassified work collects. Not a project, a waiting room.
UNFILED = "unfiled"

_UNSAFE_SLUG = re.compile(r"[^\w가-힣.-]+")


def safe_slug(raw: str) -> str:
    """Make a value usable as a filename.

    claude-mem's project field carries worktree paths such as
    'ui-skills/2026-06-27-adcker4'. Used as is, it creates subdirectories, so
    pages scatter and index links break. In the real data 5 of 28 had this shape.

    Lives here rather than in compiler because it is one half of the project
    identity below, and identity has to be shared by every writer and reader.
    compiler re-exports it for the callers that already import it from there.
    """
    return _UNSAFE_SLUG.sub("-", raw).strip("-") or "unnamed"


def host() -> str:
    """A stable short name for this machine.

    Used as the event_id namespace. claude-mem's rowid starts at 1 on every
    machine, so without mixing in the host, different sessions get the same
    event_id and one of them quietly disappears through deduplication.
    """
    raw = os.environ.get("LLMWIKI_HOST") or socket.gethostname().split(".")[0]
    return re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower() or "unknown"


def home() -> Path:
    return Path(os.environ.get("LLMWIKI_HOME", Path.home() / ".local/share/llmwiki"))


DEFAULT_VAULT = Path.home() / "Documents/llmwiki"


def vault(home_dir: Path | None = None) -> Path:
    """Vault path. env > config.toml > default.

    home() is the bootstrap point, so it is settable only through env - finding
    the config requires knowing that location first, so there is no other way.
    The vault is just a setting, though, so it lives in config.toml. That way the
    CLI, the hooks, and launchd all see the same answer.

    Back when it was env-only, they diverged. launchd and hooks do not read
    ~/.zshrc, so setting LLMWIKI_VAULT in the shell made only hand-typed commands
    use the new path while the nightly job kept writing to the default one. Two
    vaults growing separately, and nobody reports it. env now remains only for
    one-off runs and tests.
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
    """Anchor a relative path to the directory holding the config.

    Left as is, a relative path becomes a different vault depending on the
    process's cwd - compile runs in the checkout, doctor where the user stood,
    hooks somewhere else again. When the same setting resolves to different
    absolute paths, the vault splits and the check raises a false swap alarm.
    home is the same wherever you run from, so it is the anchor.
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
    # An empty string means "not set". With a Path default, a Config() built
    # without a config would drag this machine's home path around with it.
    vault: str = ""

    def resolve_project(self, raw: str) -> str:
        """Apply the mapping first, then check the result against the blocklist.

        Blocking only suppresses a page; it does not erase the record. claude-mem
        uses the last name of the session cwd as the project, so starting a
        session outside a project folder attaches a name like 'Documents' or
        'yongjae'. That does not mean junk, it means the starting point was
        shallow - there were actually 235 pieces of work under those names.
        Blocked ones collect under UNFILED, and where they came from is kept as
        origin so a mapping can bring them back later.
        """
        slug = self.mapping.get(raw, raw)
        return UNFILED if slug in self.blocklist else slug

    def project_id(self, raw: str) -> str:
        """The single canonical project identity: mapping, blocklist, then slug.

        compile keys project pages off this, and the SessionStart hook derives
        its injection filter from it - but 'llmwiki new' used to skip it and
        store the raw --project string, so the two were compared with == while
        being produced by different code. A directory named 'My Project' became
        'My-Project' on the page and stayed 'My Project' on the task, and that
        project got zero task injection forever without ever saying so.

        Applied at every write and again at every read. The read side is not
        redundant: task pages already in the vault still hold raw values, and
        normalizing them on the way in is what keeps them from being orphaned.

        Idempotent for the values it produces - a slugged name is not itself a
        mapping key - which is what makes the double application safe.
        """
        return safe_slug(self.resolve_project(raw))


def load(home_dir: Path) -> Config:
    path = home_dir / "config.toml"
    data: dict = {}
    if path.exists():
        # tomllib exists only on 3.11+. Taking that dependency just by importing
        # the module kills every test that imports llmwiki on such a Python.
        # In the test that blocks tomllib and runs verify.sh, 21 unit tests
        # actually collapsed. It is needed only to read the config, so import here.
        try:
            import tomllib
        except ModuleNotFoundError as exc:  # pragma: no cover - never hit on 3.11+
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
