from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "parse_feed.py"


def load_module():
    spec = importlib.util.spec_from_file_location("parse_feed", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParseFeedTest(unittest.TestCase):
    def test_parses_rss_without_third_party_packages(self) -> None:
        module = load_module()
        entries = module.parse_entries(
            b"""<rss><channel>
            <item><title>First item</title><link>https://example.test/1</link></item>
            <item><title>Second item</title><link>https://example.test/2</link></item>
            </channel></rss>""",
            limit=1,
        )

        self.assertEqual(entries, [{"title": "First item", "link": "https://example.test/1"}])

    def test_parses_atom_namespaces_and_href_links(self) -> None:
        module = load_module()
        entries = module.parse_entries(
            b"""<feed xmlns="http://www.w3.org/2005/Atom">
            <entry><title>Atom item</title><link rel="alternate" href="https://example.test/a" /></entry>
            </feed>""",
            limit=5,
        )

        self.assertEqual(entries, [{"title": "Atom item", "link": "https://example.test/a"}])

    def test_cli_fails_closed_on_malformed_xml(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input="<rss>",
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("invalid feed XML", completed.stderr)


if __name__ == "__main__":
    unittest.main()
