# Public career and company lookup

Use for public job/company/person pages when the user asks for hiring-market or career context.

> **Work-scope (NAVER) guard:** LinkedIn scraping and Jina (`r.jina.ai`) are forbidden in work scope. Note that `mcporter`-invoked MCPs run as a separate process and are NOT covered by `deniedMcpServers`, so a denied MCP like `linkedin-scraper` can still be launched here and bypass the denial — do not use it for internal or policy-restricted lookups. Route non-public work lookups through `agent-browser --profile "$HOME/.local/share/agent-browser/profiles/work" open <URL>` locally. Never reuse the personal or daily Chrome profile.

## LinkedIn MCP, if configured

```bash
mcporter call 'linkedin-scraper.get_person_profile(linkedin_url: "https://linkedin.com/in/username")'
mcporter call 'linkedin-scraper.search_people(keyword: "AI engineer", limit: 10)'
mcporter call 'linkedin-scraper.get_company_profile(linkedin_url: "https://linkedin.com/company/company")'
mcporter call 'linkedin-scraper.search_jobs(keyword: "software engineer", limit: 10)'
```

Use only with valid authentication and only for allowed, public-professional research. Do not collect sensitive personal data.

## Public fallback

```bash
curl -s "https://r.jina.ai/https://linkedin.com/company/company"
mcporter call 'exa.web_search_exa(query: "site:linkedin.com/company company name", numResults: 5)'
```

LinkedIn frequently blocks readers; report failures as data gaps.
