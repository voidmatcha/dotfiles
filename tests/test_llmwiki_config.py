from __future__ import annotations

import importlib.util
import sys
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "llmwiki" / "config.py"
SPEC = importlib.util.spec_from_file_location("llmwiki_config", SCRIPT)
assert SPEC and SPEC.loader
CFG = importlib.util.module_from_spec(SPEC)
# dataclasses 가 field(default_factory=...) 를 해석할 때 sys.modules 를 뒤지므로
# exec_module 전에 등록해야 한다. 등록하지 않으면 AttributeError 가 난다.
sys.modules[SPEC.name] = CFG
SPEC.loader.exec_module(CFG)


def _has_tomllib() -> bool:
    try:
        import tomllib  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


# config.toml 을 실제로 파싱하는 테스트는 tomllib(3.11+) 없이는 성립하지 않는다.
# 코드가 조용히 기본값으로 넘어가지 않고 소리 내어 실패하는 것이 옳으므로,
# 약화하는 대신 여기서 건너뛴다.
requires_tomllib = unittest.skipUnless(_has_tomllib(), "tomllib (python 3.11+) 필요")


class ConfigTest(unittest.TestCase):
    def test_defaults_apply_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = CFG.load(Path(d))
            self.assertEqual(c.active_threshold, 5)
            self.assertEqual(c.unclassified_days, 14)
            self.assertEqual(c.index_max_chars, 8000)
            self.assertEqual(c.archive_days, 180)
            self.assertEqual(c.stale_days, 7)
            self.assertEqual(c.blocklist, frozenset())
            self.assertEqual(c.mapping, {})

    @requires_tomllib

    def test_file_values_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text(
                'blocklist = ["yongjae", "Documents"]\n'
                "active_threshold = 9\n"
                "[mapping]\n"
                'llmwiki-wt1 = "llmwiki"\n',
                encoding="utf-8",
            )
            c = CFG.load(Path(d))
            self.assertEqual(c.blocklist, frozenset({"yongjae", "Documents"}))
            self.assertEqual(c.active_threshold, 9)
            self.assertEqual(c.mapping["llmwiki-wt1"], "llmwiki")
            self.assertEqual(c.unclassified_days, 14)

    @requires_tomllib

    def test_resolve_maps_then_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text(
                'blocklist = ["junk"]\n[mapping]\nraw = "junk"\n', encoding="utf-8"
            )
            c = CFG.load(Path(d))
            # 매핑이 먼저다: raw -> junk -> 차단. 차단은 버리는 것이 아니라
            # unfiled 로 보내는 것이므로 None 이 아니다.
            self.assertEqual(c.resolve_project("raw"), CFG.UNFILED)
            self.assertEqual(c.resolve_project("keep"), "keep")


if __name__ == "__main__":
    unittest.main()


class VaultResolutionTest(unittest.TestCase):
    """볼트 경로는 한 곳에서만 정해져야 한다.

    env 만으로 바꾸면 CLI 는 새 경로를, launchd 와 훅은 기본 경로를 쓴다.
    둘 다 셸 rc 를 읽지 않기 때문이다. 실측으로 확인했다 - LLMWIKI_VAULT 를
    준 compile 이 대체 경로에 볼트를 통째로 만들었고 기본 볼트도 그대로
    남아 있었다. 갈라진 것을 아무도 알려주지 않는다.
    """

    @requires_tomllib

    def test_config_key_decides_the_vault(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "config.toml").write_text('vault = "/tmp/from-config"\n', encoding="utf-8")
            self.assertEqual(CFG.vault(home), Path("/tmp/from-config"))

    @requires_tomllib

    def test_env_overrides_config_for_one_off_runs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "config.toml").write_text('vault = "/tmp/from-config"\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {"LLMWIKI_VAULT": "/tmp/from-env"}):
                self.assertEqual(CFG.vault(home), Path("/tmp/from-env"))

    def test_falls_back_to_default_without_config_or_env(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if k != "LLMWIKI_VAULT"}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(CFG.vault(Path(d)), Path.home() / "Documents/llmwiki")

    @requires_tomllib

    def test_tilde_in_config_is_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "config.toml").write_text('vault = "~/elsewhere/wiki"\n', encoding="utf-8")
            self.assertEqual(CFG.vault(home), Path.home() / "elsewhere/wiki")

    @requires_tomllib
    def test_relative_vault_is_anchored_to_home_not_cwd(self) -> None:
        """상대경로는 cwd 에 따라 다른 볼트가 된다.

        compile 은 체크아웃에서, doctor 는 사용자가 있는 곳에서, 훅은 또
        다른 곳에서 돈다. 같은 설정이 서로 다른 절대경로로 풀리면 볼트가
        갈라지고 검사는 거짓 교체 경보를 낸다. config 파일이 있는 디렉터리를
        기준으로 삼는다 - cwd 와 달리 이것은 어디서 실행하든 같다.
        """
        import os
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "state"
            home.mkdir()
            (home / "config.toml").write_text('vault = "wiki"\n', encoding="utf-8")
            here = os.getcwd()
            try:
                os.chdir(tempfile.gettempdir())
                first = CFG.vault(home)
            finally:
                os.chdir(here)
            second = CFG.vault(home)
            self.assertEqual(first, second)
            self.assertEqual(first, home / "wiki")
