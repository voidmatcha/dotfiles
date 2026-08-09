from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path


def run(vault: Path, home: Path, dest: Path, keep: int = 14, label: str | None = None) -> Path:
    stamp = label or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = dest / stamp
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    if vault.exists():
        shutil.copytree(vault, target / "vault")
    if home.exists():
        shutil.copytree(home, target / "home",
                        ignore=shutil.ignore_patterns("snapshots"))
    existing = sorted((p for p in dest.iterdir() if p.is_dir()), key=lambda p: p.name)
    for stale in existing[:-keep] if keep > 0 else []:
        shutil.rmtree(stale)
    return target
