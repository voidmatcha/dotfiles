# GitHub and developer surfaces

Prefer `gh` for public GitHub repositories, issues, PRs, Actions, releases, and API calls.

```bash
gh search repos "query" --sort stars --limit 10
gh search code "query" --language python --limit 10
gh repo view owner/repo
gh issue list -R owner/repo --state open
gh issue view 123 -R owner/repo
gh pr list -R owner/repo --state open
gh pr view 123 -R owner/repo
gh pr checks 123 --repo owner/repo
gh run list --repo owner/repo --limit 10
gh run view RUN_ID --repo owner/repo --log-failed
gh release list --repo owner/repo
gh api repos/owner/repo
```

Guidance:
- For this dotfiles repo, inspect local files first. Use GitHub only for upstream/public comparison.
- Do not fetch or paste private repository content unless the user explicitly authorizes it and the surface is appropriate.
- Use `--json` when a compact structured result is enough.
