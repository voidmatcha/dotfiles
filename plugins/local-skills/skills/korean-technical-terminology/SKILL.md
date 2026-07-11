---
name: korean-technical-terminology
description: "Review and edit Korean technical docs, READMEs, UI copy, and prompts when terminology sounds machine-translated or a canonical English term was unnecessarily translated. Classify each disputed term as canonical English to preserve, established Korean to keep, or an awkward calque to rewrite naturally. Also strips surface AI-tell symbols from Korean prose — em/en dashes and spaced --, arrows (→), curly/smart quotes, ellipsis (…), and middle-dot (·) bullets or noun enumerations. Use for 기술 용어, 번역투, 직역, 영어로 써야 할 표현, 원어 유지, 한글화가 어색함, 용어 통일, 화살표 제거, em대시 없애, 가운뎃점 없애, AI 티 기호, AI slop 기호, Korean technical writing, or terminology review. Do not use as a general spelling or tone checker."
---

# Korean Technical Terminology

Review Korean technical prose without blindly translating every English term or reverting every Korean term to English. Preserve precision, searchability, and natural Korean at the same time.

Provenance: Mode: original local skill. Public terminology examples were verified against scoped React Korean docs, MDN Korean docs, and web.dev examples; they are evidence for the decision method, not a universal glossary. No upstream skill text or code was copied.

## Boundary

Use this skill for terminology decisions in technical writing:

- canonical product, API, protocol, package, and framework names
- English search terms whose literal Korean form loses precision
- established Korean technical terms backed by maintained documentation
- awkward calques and machine-translated phrases
- inconsistent terminology across headings, tables, examples, and FAQs

Do not use it for ordinary spelling, honorifics, or broad prose humanization (rhythm, tone, sentence-level rewriting). Route those to a grammar, style, or Korean humanization skill instead.

**In scope (punctuation exception):** surface AI-tell symbols in Korean prose — em/en dashes and spaced `--`, arrows (`→`), curly/smart quotes, ellipsis (`…`), and the middle-dot (`·`) used as a leading bullet or to chain a noun enumeration. These are mechanical deletions, not tone edits. See "Surface AI-tell symbols" below.

## Surface AI-tell symbols

These symbols read as machine/AI output in Korean prose and are removed by default. This is deletion, not a terminology decision, so it runs independently of the classify step.

**Default: remove all of these from prose.**

- **Em/en dash (`—` `–`) and spaced `--`** — replace with a comma, period, colon, or parentheses, or split into separate sentences. Korean prose almost never needs them.
- **Arrows (`→` `⟶` `➔`)** — write the relation out ("A에서 B로", "A는 B가 된다", "A하면 B한다") or split into sentences.
- **Curly/smart quotes (`" "` `' '`)** — use straight quotes or Korean corner brackets (「」 『』); if the quotes were only emphasis, drop them.
- **Ellipsis (`…`)** — end with a period or delete. Keep only for a genuine trailing-off in essay/fiction voice (1–2 max).
- **Middle-dot (`·`)** — remove in both forms:
  - as a leading bullet ("· 첫째 …"): convert to prose or a standard Markdown bullet.
  - as a noun enumeration ("ChatGPT·Claude·Gemini 등", "탐지·분류·검증"): rewrite with commas plus one of "~나 / ~와·과 / ~등", e.g. "ChatGPT, Claude, Gemini 같은".

**Preserve (do not touch):** dashes, arrows, quotes, and middle-dots inside code, locators (`data-testid`), table separators (`| --- |`), math/chemical formulas, diagrams (`a → b`), string literals, and official proper-noun spellings.

## Parenthetical period placement (Korean)

When a parenthetical is a trailing aside or citation at or after the end of a Korean sentence, put the period **before** the opening paren, not after the closing paren.

- Rewrite `문장입니다 (부연).` → `문장입니다. (부연)`
- Applies to trailing notes, source citations, and "(PR #5290)"-style references that sit at a sentence boundary.
- **Skip** when the parenthesis is a grammatical part of the sentence — a gloss or subject (`React(리액트)는 …`), an inline unit (`8080(포트)`), or a mid-sentence qualifier — where no sentence-final period is involved.

## Workflow

1. **Fix the edit scope**
   - Identify the target files, audience, and requested language.
   - Preserve code blocks, CLI commands, identifiers, URLs, file names, and package names exactly unless the user explicitly asks to change them.

2. **Inventory disputed terms**
   - Find awkward literal translations, unnecessary transliterations, canonical English names translated into Korean, and inconsistent variants of the same concept.
   - Also flag surface AI-tell symbols for removal (see "Surface AI-tell symbols"): dashes, arrows, curly quotes, ellipsis, and middle-dot bullets or enumerations in prose.
   - Inspect every occurrence before choosing a replacement so headings, tables, body text, and FAQs stay aligned.

3. **Classify before editing**
   - **Canonical English:** keep product names, API/protocol identifiers, code symbols, and exact search terms in English when translation reduces precision or discoverability.
   - **Established Korean:** use the stable Korean term when authoritative Korean documentation or a maintained glossary for the same project and domain consistently does so.
   - **Natural rewrite:** replace an awkward calque with a natural Korean phrase when neither the current Korean form nor raw English improves the sentence.

4. **Research only ambiguous decisions**
   - Read `references/decision-guide.md` before changing disputed technical terms.
   - Check official Korean documentation or a maintained Korean glossary first.
   - Check the upstream English name and source context second.
   - Treat a project glossary as authoritative only within its documented scope; do not promote a React or web-platform translation into a universal software term without independent evidence.
   - Use public community frequency only as supporting evidence, never as the primary authority.
   - When local evidence is insufficient, use `agent-reach` within its public-only boundary and record the URLs that materially changed the decision.
   - If no settled Korean usage exists and exact lookup matters, retain the English term, usually in backticks.

5. **Edit conservatively**
   - Change the smallest coherent set of occurrences.
   - Do not invent Korean terms by translating dictionary components one by one.
   - Do not turn established Korean terms into English merely because the document is technical.
   - Keep one chosen form for one concept unless quoting an external source.

6. **Verify the result**
   - Search for old and new variants across the edited scope.
   - Confirm code, identifiers, links, Markdown structure, and examples were not changed unintentionally.
   - Run the repository's formatter, lint, docs build, or link checker when available.
   - Report any unresolved terminology choice as a verification gap instead of guessing.

## Output

Report only decisions that help review the change:

```markdown
## 변경
- <file>: <summary>

## 용어 판단
- `<before>` → `<after>`: <canonical English | established Korean | natural rewrite> — <reason/source>

## 검증
- <search/check/test and result>

## 남은 모호성
- <none, or unresolved term and why>
```

Keep the final prose natural. The decision labels are for the review report, not text that must be inserted into the document.
