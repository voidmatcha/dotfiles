# Public web reading

Use for public pages, articles, docs, RSS feeds, and WeChat articles.

## Jina Reader

```bash
curl -s "https://r.jina.ai/http://example.com/article"
curl -s "https://r.jina.ai/https://example.com/article"
```

Use only for public URLs. Do not send internal, localhost, company, authenticated, or secret-bearing pages.

> **Work-scope (NAVER) guard:** Jina (`r.jina.ai`) and other hosted readers/scrapers are forbidden for `*.navercorp.com`, internal, or authenticated URLs. Note that `mcporter`-invoked MCPs run as a separate process and are NOT covered by `deniedMcpServers`, so they can bypass the denial — do not route internal or policy-restricted lookups through them. Fetch non-public pages locally with `defuddle` or `agent-browser open <URL> --profile "Default" --allowed-domains <host>`.

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
python3 - <<'PY'
import feedparser
for e in feedparser.parse('FEED_URL').entries[:5]:
    print(f'{e.title} — {e.link}')
PY
```
