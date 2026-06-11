# code-server worktree workspace

Use code-server as a browser-based worktree dashboard by generating a
multi-root VS Code workspace from `git worktree list`.

## Commands

`scripts/statusline.sh` installs these helpers into `~/.local/bin`:

- `agent-worktrees --print` — generate and print
  `~/.cache/agent-worktrees/<repo>.worktrees.code-workspace`.
- `agent-worktrees --url` — print a code-server URL for the generated
  multi-root workspace.
- `agent-worktrees --open` — open the generated workspace URL in the default
  browser.
- `agent-worktree-url [branch]` — print a code-server URL for a specific
  branch's worktree. Defaults to the current branch.
- `agent-worktree-link [branch]` — print an OSC-8 terminal hyperlink labelled
  with the branch name. Use this in HUD/statusline surfaces that preserve
  terminal hyperlinks.
- `agent-worktree-cmux [branch]` — open the branch worktree URL in a cmux
  browser split using `cmux browser open-split`.
- `agent-worktrees-cmux` — open the generated multi-root workspace URL in a
  cmux browser split.

The generated `.code-workspace` is regular JSON:

```json
{
  "folders": [
    {
      "name": "dotfiles [main]",
      "path": "/Users/user/work/dotfiles"
    },
    {
      "name": "dotfiles-feature [feature/demo]",
      "path": "/Users/user/worktrees/dotfiles-feature"
    }
  ],
  "settings": {
    "git.openRepositoryInParentFolders": "always"
  }
}
```

## code-server extensions

`scripts/code-server.sh` installs the browser IDE extensions that make this
usable:

- `jackiotyu.git-worktree-manager`
- `eamodio.gitlens`
- `mhutchie.git-graph`

The script is called from `scripts/dev.sh` and is safe to re-run.

## HUD/link behavior

Codex's built-in `[tui].status_line = ["git-branch", ...]` item is not a
custom clickable component. The portable integration point is therefore the
URL/link helper:

```bash
agent-worktree-link           # hyperlink for the current branch worktree
agent-worktree-link feature/x # hyperlink for a specific branch worktree
```

Claude/statusline/HUD surfaces that render OSC-8 hyperlinks can display this
output directly. For Codex's built-in statusline, keep the branch text there
and use `agent-worktrees --open` or a custom HUD wrapper for click behavior.

## cmux-deck / cmux web

Do not rely on OSC-8 terminal hyperlink support for cmux-deck. Use the cmux
browser helpers, which call cmux directly:

```bash
agent-worktree-cmux           # current branch worktree in a cmux browser split
agent-worktree-cmux feature/x # selected branch worktree
agent-worktrees-cmux          # all worktrees as a multi-root workspace
```

Aliases from `.zshrc`:

```bash
wtdeck     # agent-worktree-cmux
wtdeckall  # agent-worktrees-cmux
```
