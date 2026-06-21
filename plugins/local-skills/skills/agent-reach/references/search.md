# Public search

Use for current public web evidence, especially when local repo search cannot answer the question.

## Exa via mcporter

```bash
mcporter call 'exa.web_search_exa(query: "query", numResults: 5)'
mcporter call 'exa.get_code_context_exa(query: "code question", tokensNum: 3000)'
```

Guidance:
- Use official/upstream sources first when the question is about a specific product, API, library, or release.
- Keep result counts small. Open only the pages needed for evidence.
- Do not query private/company/internal text or URLs through hosted search.
- For Korean/community context, search can identify candidates, but verify with primary sources before making claims.
