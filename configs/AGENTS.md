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

Three indexers cover this space — pick by intent, not by familiarity. They overlap on
symbol lookup but each wins on a different axis. **codegraph and serena are
complementary, not competing**: codegraph answers breadth ("how does X reach Y across
the whole repo?") in one call; serena answers depth ("show me this exact symbol and
let me edit it") with LSP-grade accuracy. Use codegraph FIRST for exploration, then
serena for the precise edit.

| Task | Tool | Why |
|------|------|-----|
| "How does X reach Y" / "where does this flow go" / architecture / trace across files | **codegraph MCP** (`codegraph_context`, `codegraph_trace`, `codegraph_explore`) | Pre-indexed graph answers in 3–10 tool calls vs. 30+ for grep+Read fan-out. ~35% cheaper / ~70% fewer tool calls on large repos. Read-only. Run `codegraph init -i` in a new project once. |
| Cross-file rename, refactor, **edit by symbol** | **serena MCP** (`replace_symbol_body`, `rename`, `insert_before_symbol`, …) | Type-aware via LSP, edits safely. codegraph can't edit. |
| Find a specific symbol + read its body to edit | **serena** `find_symbol` (include_body=true) | LSP-accurate, real-time. codegraph's `codegraph_node` works too but its watcher debounces 2s — serena is fresher for just-written code. |
| "Who calls / references this symbol?" | **serena** `find_referencing_symbols` if you trust LSP and the lookup is single-language; **codegraph** `codegraph_callers` if you need cross-language hops (RN bridge, JNI, ObjC↔Swift) or LSP is unavailable | LSP gives exact type-aware refs; codegraph gives broader graph reach. Prefer LSP when both work. |
| iOS / React Native cross-language bridges (Swift↔ObjC, RN bridge/Turbo/Fabric, Expo Modules) | **codegraph** | LSP stops at language boundaries; codegraph synthesizes the hops |
| Find URL → handler mappings (Django/Flask/FastAPI/Express/NestJS/Rails/Spring/Gin/Axum/…) | **codegraph** | Recognizes framework route files and emits explicit edges |
| Grep across files, list dir, simple Bash | Claude's built-in `Grep`/`LS`/`Bash` tools | serena's basic equivalents are auto-disabled to avoid duplication |
| Understand structure of unfamiliar **non-code** content (docs, PDFs, papers folder) | **graphify** (`/graphify <dir>`) | Same idea as codegraph but for arbitrary content. For pure code, codegraph wins (specialized). |
| Audit `CLAUDE.md` files vs current code | `claude-md-improver` skill (auto-triggered by "audit CLAUDE.md") | Plugin from `claude-md-management@claude-plugins-official` |
| Capture session learnings into `CLAUDE.md` | `/claude-md-management:revise-claude-md` slash command | Same plugin |

**Decision shortcut.** Faced with "explain / understand / trace": reach for **codegraph** first.
Faced with "rename / edit / refactor": reach for **serena**. Faced with "I just need 5 lines from
a file I already know": Read.

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

- **serena** (MCP) — semantic code navigation and **editing** backed by LSP. Use
  for cross-file renames, symbol lookups, reference searches, and refactors
  where text-level edits would be fragile. Semantic tools are active by
  default; serena's redundant basic utilities (read/grep/ls/bash equivalents)
  are auto-disabled because Claude Code already covers them. The shell
  wrapper in `.zshrc` injects serena's system-prompt-override (to counter
  Opus's strong bias toward built-in tools) and also defaults every `claude`
  launch to `--settings '{"ultracode":true}'` (xhigh effort + standing
  dynamic-workflow orchestration; opt out per-session with
  `CLAUDE_ULTRACODE=0`). https://github.com/oraios/serena
- **codegraph** (MCP) — pre-indexed knowledge graph (tree-sitter + SQLite) for
  **exploration** of large or cross-language codebases. Read-only;
  complements serena. Run `codegraph init -i` in each project once; the
  watcher auto-syncs on save (~2s debounce). Strong on framework route
  mapping (Django/Flask/FastAPI/Express/NestJS/Rails/Spring/…) and iOS/RN
  cross-language bridges that LSP can't follow. ~35% cheaper / ~70% fewer
  tool calls than grep+Read on architecture questions over big repos.
  https://github.com/colbymchenry/codegraph
- **graphify** (Claude Code skill, `/graphify`) — build a queryable knowledge
  graph from any folder (code, docs, PDFs, images). Use for **mixed-content**
  folders (docs + papers + small code samples) where codegraph's
  code-specialized indexer doesn't fit. For pure code, reach for codegraph
  first — it has framework awareness and cross-language bridging that
  graphify lacks. 71x fewer tokens per query than re-reading raw files.
  https://github.com/safishamsi/graphify
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
- Keep enabled MCPs lean per project — aim for <10 enabled and <80 total
  active tools at any time. Past that, the model loses the ability to pick
  the right tool. Disable per-project via `/mcp` rather than uninstalling.
- Don't create stray top-level `*.md` files (NOTES.md, SUMMARY.md,
  FINDINGS.md, etc.). Named-policy files (README, CLAUDE, AGENTS,
  CONTRIBUTING, LICENSE, CHANGELOG, SKILL, SECURITY) and files under
  `docs/`, `skills/`, `.claude/`, `agents/`, `commands/` are fine; anything
  else needs explicit user approval. (Enforced by pretool-guard.sh.)

## Commit message protocol

For any non-trivial commit (more than a one-line fix), include the trailer
block below. The trailers turn `git log` into a free decision log — future
spelunkers can `git log --grep='Rejected:'` to see what was *not* taken.

```
<subject line — imperative, ≤72 chars>

<body — what changed and why, wrap at 80>

Constraint: <external limits you worked under — API shapes, compliance,
  framework guarantees. Omit if there were none.>
Rejected: <alternatives you considered but discarded + one-line reason.
  Omit if no real alternatives existed.>
Confidence: <high | medium | low>
Scope-risk: <code outside this diff that could plausibly break. "none"
  is a valid answer if you really checked.>
Not-tested: <things you couldn't verify (env, integration, race). "none"
  is valid.>
```

Trivial diffs (typo fix, dependency bump, formatting-only change) skip
the trailer block. Use judgment — if the commit touched logic, write the
trailers.
