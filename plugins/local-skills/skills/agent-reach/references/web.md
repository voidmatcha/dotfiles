# Public web reading

Use for public pages, articles, docs, RSS feeds, and WeChat articles.

## Jina Reader

```bash
curl -s "https://r.jina.ai/http://example.com/article"
curl -s "https://r.jina.ai/https://example.com/article"
```

Use only for public URLs. Do not send internal, localhost, company, authenticated, or secret-bearing pages.

> **Work-scope (NAVER) guard:** Jina (`r.jina.ai`) and other hosted readers/scrapers are forbidden for `*.navercorp.com`, internal, or authenticated URLs. Note that `mcporter`-invoked MCPs run as a separate process and are NOT covered by `deniedMcpServers`, so they can bypass the denial — do not route internal or policy-restricted lookups through them. Fetch non-public pages locally with `agent-browser --profile "$HOME/.local/share/agent-browser/profiles/work" open <URL>`. Keep this profile separate from personal and daily Chrome state.

Persistent authenticated profiles do not provide agent-browser's domain
containment. If strict containment is required, use a fresh unauthenticated
session with an explicit domain allowlist instead of loading saved login state.

## Web reader MCP

```bash
mcporter call 'web-reader.webReader(url: "https://example.com")'
mcporter call 'web-reader.webReader(url: "https://example.com", retain_images: true)'
mcporter call 'web-reader.webReader(url: "https://example.com", return_format: "text")'
```

## WeChat articles

```bash
mcporter call 'exa.web_search_exa(query: "keyword", numResults: 5, includeDomains: ["mp.weixin.qq.com"])'
mcporter call 'exa.crawling_exa(urls: ["https://mp.weixin.qq.com/s/ARTICLE_ID"], maxCharacters: 10000)'
```

Jina Reader is often blocked by WeChat CAPTCHA; Exa crawl or a local browser workflow may work better.

## RSS

```bash
FEED_URL="https://example.com/feed.xml"
curl --proto '=https' --proto-redir '=https' --location --fail --silent --show-error \
  --max-time 20 "$FEED_URL" \
  | python3 "$SKILL_DIR/scripts/parse_feed.py" --limit 5
```

The bundled parser accepts RSS and Atom XML on stdin and uses only the Python
standard library. This avoids assuming that the caller's Python environment has
`feedparser` installed. Fetch public HTTPS feeds only.
