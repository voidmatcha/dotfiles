---
name: agent-reach
description: "Use public web, GitHub, social/community, video, RSS, and career search surfaces from the CLI/MCP when local repo evidence is not enough. Routes to public-only research tools while avoiding internal/company URLs and secret-bearing pages."
license: unknown
compatibility: "Requires public network access; optional gh, mcporter, yt-dlp, and platform-specific CLIs unlock additional channels."
metadata:
  dotfiles.provenance.upstream: https://github.com/Panniantong/agent-reach
  dotfiles.provenance.mode: adapted
  dotfiles.provenance.local-changes: "Rewritten as a public-only routing skill with company URL guards, local tool fallbacks, and non-mutating health checks."
---

# Agent Reach

Use this skill when the task needs current public internet evidence beyond local repository files: web search, page reading, GitHub discovery, social/community signal, video subtitles, RSS, or public career/company pages.

Provenance: Upstream: https://github.com/Panniantong/agent-reach; License: unknown; Mode: adapted; Local changes: public-only routing, company URL guards, local fallbacks, and non-mutating health checks.

## Safety boundary

- Public sources only by default. Do not send company, client, localhost, private repository, authenticated, or secret-bearing URLs through hosted readers/search tools such as Exa, Jina Reader, or third-party scrapers.
- Work-scope (NAVER): for `*.navercorp.com`, internal, or authenticated URLs, never use Jina (`r.jina.ai`) or any hosted reader/scraper. Fetch locally with `defuddle` or `agent-browser open <URL> --profile "Default" --allowed-domains <host>` instead. See the routing table in `company/configs/AGENTS-company.md`.
- Prefer official documentation, upstream repositories, release notes, and source pages before social summaries.
- Treat CLI/social results as leads until opened and checked. Report unavailable tools instead of claiming a channel worked.
- Use `/tmp` for temporary fetched content. Use `~/.agent-reach/` only for persistent tool state.
- Do not bulk scrape, bypass access controls, or collect personal data beyond what the user explicitly asks and is allowed to process.

## Route by task

| Need | Read next | Typical tools |
| --- | --- | --- |
| General public web search or code-aware search | [`references/search.md`](references/search.md) | `mcporter` Exa tools, search snippets |
| Read a public URL, article, RSS feed, or WeChat article | [`references/web.md`](references/web.md) | Jina Reader, web-reader MCP, Exa crawl, RSS parser |
| GitHub repositories, PRs, issues, releases, CI logs | [`references/dev.md`](references/dev.md) | `gh search`, `gh repo`, `gh pr`, `gh run`, `gh api` |
| Reddit, V2EX, X/Twitter, Xiaohongshu, Douyin, Weibo, Bilibili signals | [`references/social.md`](references/social.md) | platform CLIs/MCPs when installed |
| YouTube/Bilibili/podcast metadata, subtitles, or comments | [`references/video.md`](references/video.md) | `yt-dlp`, `bili`, transcript helpers |
| Public LinkedIn/job/company lookup | [`references/career.md`](references/career.md) | LinkedIn MCP if authenticated; public fallback only |

## Quick checks

```bash
command -v agent-reach >/dev/null && agent-reach --version
command -v gh >/dev/null && gh auth status
command -v yt-dlp >/dev/null && yt-dlp --version
```

Do not use `agent-reach doctor` as a read-only probe. The upstream command may
re-register its generic skill under `~/.agents/skills` and `~/.claude/skills`,
overwriting or duplicating this adapted local skill. Run it only during explicit
upstream setup; afterward reinstall local skills and compare the active trees.

If a command is missing, use the nearest available public alternative and state the gap.
