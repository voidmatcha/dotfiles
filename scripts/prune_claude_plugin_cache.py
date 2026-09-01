#!/usr/bin/env python3
"""Remove Claude plugin versions explicitly orphaned for at least seven days."""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path
from typing import NamedTuple


class PruneResult(NamedTuple):
    removed_count: int
    removed_bytes: int


def _validated_cache_root(root: Path, *, require_suffix: bool = False) -> Path:
    expanded = root.expanduser()
    if require_suffix and expanded.parts[-3:] != (".claude", "plugins", "cache"):
        raise ValueError("--root must end in .claude/plugins/cache")

    # Never follow a caller-controlled cache-root symlink into another tree.
    # For the CLI, also protect the two policy-bearing parent components.
    boundaries = [expanded]
    if require_suffix:
        boundaries.extend((expanded.parent, expanded.parent.parent))
    if any(path.is_symlink() for path in boundaries):
        raise ValueError("cache root and its .claude/plugins parents must not be symlinks")
    return expanded.resolve(strict=False)


def _size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def prune(root: Path, *, min_age_days: float = 7, dry_run: bool = False) -> PruneResult:
    root = _validated_cache_root(root)
    if not root.is_dir():
        return PruneResult(0, 0)

    cutoff = time.time() - min_age_days * 86400
    removed_count = removed_bytes = 0
    for marker in root.glob("*/*/*/.orphaned_at"):
        version = marker.parent
        try:
            parts = version.relative_to(root).parts
        except ValueError:
            continue
        if len(parts) != 3 or marker.is_symlink() or version.is_symlink():
            continue
        try:
            version.resolve(strict=True).relative_to(root)
            if not marker.is_file() or marker.stat().st_mtime > cutoff:
                continue
            size = _size(version)
            if not dry_run:
                shutil.rmtree(version)
        except (FileNotFoundError, ValueError):
            continue
        removed_count += 1
        removed_bytes += size
    return PruneResult(removed_count, removed_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".claude/plugins/cache",
    )
    parser.add_argument("--min-age-days", type=float, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        expanded = _validated_cache_root(args.root, require_suffix=True)
    except ValueError as exc:
        parser.error(str(exc))
    if args.min_age_days < 7:
        parser.error("--min-age-days must be at least 7")

    result = prune(expanded, min_age_days=args.min_age_days, dry_run=args.dry_run)
    verb = "Would prune" if args.dry_run else "Pruned"
    print(f"{verb} {result.removed_count} old orphaned cache version(s) "
          f"({result.removed_bytes // 1024 // 1024} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
