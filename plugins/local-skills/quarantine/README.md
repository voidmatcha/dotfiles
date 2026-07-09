# Quarantined local skill assets

Content under this directory is retained for review or salvage but is outside the
published `skills/` root and must not auto-trigger.

## asset-improver

Quarantined because the advertised workflow is not currently executable or safe:

- it assumes `skills-janitor` and `deep-research` skill names that are not
  consistently available across Claude and Codex (`deep-research` is absent and
  the installed `skills-janitor` surface is Claude-specific);
- its behavioral harness contains a machine-specific absolute path;
- its freeze/recovery flow can commit and use destructive Git reset operations;
- the bundled scripts have no regression suite proving the end-to-end contract.

Do not restore it to `skills/` until dependencies are resolved portably, Git
recovery is non-destructive, and behavioral plus transaction tests pass.
