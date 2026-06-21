# Public social and community signals

Use social/community channels for trend discovery, sentiment, examples, and leads. Treat results as leads, not final evidence, until opened and checked.

## Reddit

```bash
rdt search "query" --limit 10
rdt read POST_ID
```

## V2EX

```bash
curl -s "https://www.v2ex.com/api/topics/hot.json" -H "User-Agent: agent-reach/1.0"
```

## X / Twitter

```bash
twitter search "query" --limit 10
```

Only use if the CLI is installed and authenticated. Do not claim coverage if the tool is missing or rate-limited.

## Xiaohongshu / Douyin / Weibo / Bilibili

Use installed platform CLIs or MCPs only when available. Prefer small searches and cite opened items, not just search-result counts.

```bash
xhs search "query"
xhs read NOTE_ID_OR_URL
bili search "query" --type video -n 5
bili hot -n 10
```

Avoid personal-data collection and bulk scraping.
