#!/usr/bin/env python3
"""Parse RSS or Atom XML from stdin without third-party packages."""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from typing import Iterable


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if local_name(child.tag) == name:
            return clean_text("".join(child.itertext()))
    return ""


def entry_link(element: ET.Element) -> str:
    fallback = ""
    for child in element:
        if local_name(child.tag) != "link":
            continue
        href = clean_text(child.get("href"))
        text = clean_text("".join(child.itertext()))
        candidate = href or text
        if not candidate:
            continue
        if child.get("rel", "alternate") == "alternate":
            return candidate
        fallback = fallback or candidate
    return fallback


def feed_items(root: ET.Element) -> Iterable[ET.Element]:
    for element in root.iter():
        if local_name(element.tag) in {"item", "entry"}:
            yield element


def parse_entries(xml: bytes, limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    root = ET.fromstring(xml)
    entries: list[dict[str, str]] = []
    for item in feed_items(root):
        title = child_text(item, "title") or "(untitled)"
        link = entry_link(item)
        entries.append({"title": title, "link": link})
        if len(entries) >= limit:
            break
    return entries


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be greater than zero")
    try:
        entries = parse_entries(sys.stdin.buffer.read(), args.limit)
    except ET.ParseError as exc:
        print(f"error: invalid feed XML: {exc}", file=sys.stderr)
        return 2
    if not entries:
        print("error: feed contains no RSS items or Atom entries", file=sys.stderr)
        return 1
    for entry in entries:
        suffix = f" — {entry['link']}" if entry["link"] else ""
        print(f"{entry['title']}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
