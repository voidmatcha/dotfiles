---
name: source-provenance
description: "Track provenance for imported skills, agents, hooks, prompts, plugins, scripts, and third-party workflow assets."
---

# Source Provenance

Before adding or modifying imported agent assets, record where they came from.

## Workflow

Resolve the checkout explicitly; never assume the caller's cwd:

```bash
DOTFILES_DIR="${DOTFILES_DIR:-$HOME/work/dotfiles}"
test -f "$DOTFILES_DIR/scripts/source_provenance_audit.py"
```

1. For a new external asset, capture upstream URL, license, and whether this repo is vendoring, adapting, or only inspired by it.
2. Run `python3 "$DOTFILES_DIR/scripts/source_provenance_audit.py"` to find local assets that likely need provenance notes.
3. Prefer a short comment/frontmatter note near the adapted file over a separate top-level document.
4. If provenance is unknown, mark it as unknown and flag it as a risk instead of inventing attribution.

For Agent Skills, prefer the standard frontmatter fields `license`, `compatibility`,
and string-valued `metadata`. Store repo-specific provenance under namespaced keys:

```yaml
license: MIT
compatibility: "Requires public network access and gh."
metadata:
  dotfiles.provenance.upstream: https://github.com/example/project
  dotfiles.provenance.mode: adapted
  dotfiles.provenance.local-changes: "Added local safety and install boundaries."
```

Keep a legacy near-file provenance sentence only when the asset format cannot carry
frontmatter. Validate strict audit results with:

```bash
python3 "$DOTFILES_DIR/scripts/source_provenance_audit.py" --strict
```

## Required fields for adapted assets

- Upstream: URL or package/repo identity
- License: SPDX id or explicit unknown
- Mode: vendored, adapted, inspired-by, or original
- Local changes: one short sentence when adapted
