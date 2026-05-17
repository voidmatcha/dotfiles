If something is ambiguous, stop. State what's unclear and ask.
Don't silently pick an interpretation and run with it.

Don't touch code unrelated to the request.
Don't clean up what you didn't break.

## Tool routing (decision tree)

Pick the tool that matches the task. Each row lists trade-offs; obey them.

### "I need to read / fetch a web page"

| Source URL | First choice | Why | When to NOT use it |
|------------|--------------|-----|--------------------|
| Public article, one-off | `curl -s https://r.jina.ai/<URL>` (Jina Reader, hosted) | Fastest path, no install, LLM-clean Markdown | URL is sensitive/internal — it would transit Jina's servers |
| Sensitive / internal / corporate, or bulk | `npx defuddle parse <URL> --markdown` (local) | Page is fetched from your machine; no external rate limit | First `npx` is slow (downloads package); URL is behind auth |
| Behind auth (private app, dashboard, SSO) | `agent-browser open <URL> --profile "Default"` then `agent-browser snapshot -i` | Reuses your logged-in Chrome session (cookies, SSO) | One-off public reads — overkill |
| You want **search** results, not a specific URL | Exa MCP (`web_search_exa` tool) | Semantic search, LLM-friendly results | You already have the URL — use Jina/defuddle |
| You want one URL but already searching Exa | Exa MCP `web_fetch_exa` | Saves a round-trip vs separate fetch | Direct URL outside an Exa search context — Jina/defuddle is simpler |

### "I need to read a specific platform"

| Platform | Tool | Setup | Notes |
|----------|------|-------|-------|
| YouTube / Bilibili / 1800+ video sites | `yt-dlp --dump-json <URL>` (meta), `yt-dlp --write-sub --skip-download <URL>` (subs) | None | No auth needed |
| Twitter / X | `twitter search "query"`, `twitter read <URL>`, `twitter user <handle>` | Logged in to x.com in Chrome/Firefox (cookie auto-extracted) | Don't bulk-scrape (account flag risk) |
| Reddit | `rdt search "query"`, `rdt read <POST_ID>` | `rdt login` once (Reddit requires auth since 2024) | Returns post + comments |
| LinkedIn | `linkedin` MCP tool — Claude calls it directly | Browser auth on first MCP tool call | Low-volume only; ToS prohibits automated tools |
| RSS / Atom | `python3 -c 'import feedparser; d=feedparser.parse("<URL>"); ...'` | None (feedparser installed via dev.sh) | Blogs, YouTube channel feeds, GitHub releases, HN, Hada News |
| GitHub (any host) | `gh` CLI (`gh issue list`, `gh pr view`, `gh repo clone`, …) | `gh auth login` once | Public dotfiles uses `gh` only; on internal NAVER machines a `github` MCP is added separately (see `company/`) |

### "I need to understand or change code"

| Task | Tool | Why |
|------|------|-----|
| Cross-file rename, symbol lookup, find references, refactor | **serena MCP** (semantic, LSP-backed) | Type-aware; safer than text-level Edit |
| Grep across files, list dir, simple Bash | Claude's built-in `Grep`/`LS`/`Bash` tools | serena's basic equivalents are auto-disabled to avoid duplication |
| Understand structure of an unfamiliar codebase / docs / papers folder | **graphify** (`/graphify <dir>`) | Builds a queryable knowledge graph; 71× fewer tokens per query than re-reading raw files |
| Audit `CLAUDE.md` files vs current code | `claude-md-improver` skill (auto-triggered by "audit CLAUDE.md") | Plugin from `claude-md-management@claude-plugins-official` |
| Capture session learnings into `CLAUDE.md` | `/claude-md-management:revise-claude-md` slash command | Same plugin |

### "I need to interact with a browser"

| Use case | Tool |
|----------|------|
| Authenticated site, reuse the user's Chrome profile | `agent-browser open <URL> --profile "Default"` then `snapshot`/`click`/`fill`/etc. |
| Throwaway clean session, no auth carryover | `chrome-devtools` MCP tool |
| **Don't** use Playwright MCP (per project rule); `agent-browser` covers the same need with less weight | — |

## Available tools — reference

These are installed by this dotfiles setup. Prefer them over reinventing or
asking the user to install something new. Sources of truth for installation
are `scripts/dev.sh`, `Brewfile`, and `configs/mcp.json`.

- **serena** (MCP) — semantic code navigation and editing backed by LSP. Use
  for cross-file renames, symbol lookups, reference searches, and refactors
  where text-level edits would be fragile. Semantic tools are active by
  default; serena's redundant basic utilities (read/grep/ls/bash equivalents)
  are auto-disabled because Claude Code already covers them. The shell
  wrapper in `.zshrc` injects serena's system-prompt-override automatically
  to counter Opus 4.7's strong bias toward built-in tools. https://github.com/oraios/serena
- **graphify** (Claude Code skill, `/graphify`) — build a queryable knowledge
  graph from any folder (code, docs, PDFs, images). Use when you need to
  understand structure of a large unfamiliar codebase or document set before
  diving in. 71x fewer tokens per query than re-reading raw files. https://github.com/safishamsi/graphify
- **defuddle** (npm CLI) — extract main content from a web page as Markdown.
  Use ad-hoc via `npx defuddle parse <url> --markdown` when summarizing or
  quoting articles; prefer this over scraping raw HTML. https://github.com/kepano/defuddle
- **Jina Reader**, **Exa MCP**, **agent-browser**, and **chrome-devtools MCP** —
  see routing tables above.
- **yt-dlp**, **twitter** ([public-clis/twitter-cli](https://github.com/public-clis/twitter-cli)), **rdt** ([public-clis/rdt-cli](https://github.com/public-clis/rdt-cli)), **feedparser**, and
  **linkedin MCP** — see platform table above.
- **rtk** — CLI output compressor that auto-applies to most Bash commands via
  hook. Saves 60–90% tokens. Compressed output is what you see by default;
  use `rtk proxy <cmd>` (or run outside the hook path) when you need raw output.
- **ccusage** — `ccusage` CLI for analyzing your token usage from local JSONL.
- **wrangler** — Cloudflare Workers/Pages/R2/D1 CLI. `wrangler login` once.
- **context7** (MCP) — up-to-date library/framework docs lookup. Public host
  (`mcp.context7.com`) works anonymously; company overlay sets
  `CONTEXT7_API_KEY` from `~/.company.secrets.env` to lift rate limits.

## Hard rules

- Don't recommend tools or installs that aren't in this dotfiles setup. If
  the task genuinely needs something new, surface that as a question first.
- Don't transit sensitive/internal URLs through hosted services (Jina,
  Exa). Use the "local" alternative (defuddle, agent-browser).
- Don't bulk-scrape any platform — account-flag risk on X / Reddit /
  LinkedIn, and rate-limit risk on Jina / Exa.
