---
name: session-feedback-audit
description: "Analyze historical local Codex or Claude JSONL session logs for repeated user corrections, re-requests, execution preferences, and agent failure patterns, then turn cross-session evidence into concise anti-repeat rules. Use for historical session-feedback audit, JSONL analysis, repeated corrections, recurring instructions, 매번 요청, 반복 안 되게, 재발 방지, or requests to learn durable guidance from past agent conversations. Do not use for current-document cleanup or writing review. Built-in Korean and English pattern packs are extensible with custom JSON patterns; this is not a Korean-only writing skill."
---

# Session Feedback Audit

Mine local agent session logs for recurring feedback and convert the evidence into reusable rules that prevent the same mistakes from recurring.

## Boundary

Use this skill to answer questions such as:

- What corrections or re-requests keep appearing across sessions?
- Does the user repeatedly ask the agent to execute instead of explaining?
- Are repository, runtime, artifact, or confirmation mistakes recurring?
- Which evidence-backed rules should be added to a prompt or skill?

Do not use it to proofread a document or decide Korean technical terminology. Use a writing or terminology skill for the current document itself.

## Inputs

Accept one or more of:

- Codex or Claude `*.jsonl` session or rollout files
- directories containing JSONL files
- no explicit path, which defaults to recent Codex sessions under `~/.codex/sessions`
- an optional JSON pattern pack for another language or project vocabulary

Keep analysis local. Do not upload private logs.

The analyzer redacts authorization bearer values, sensitive JSON or assignment values, standalone OpenAI and GitHub tokens, JWTs, PEM private-key blocks, cookies, query-string tokens, and email addresses before it derives snippets, keywords, JSON, or Markdown. Explicit paths fail closed when they are missing, are not JSONL, or contain no readable JSON objects. Files written with `--out` are atomically replaced with mode `0600`.

## Workflow

1. **Locate evidence**
   - Use paths supplied by the user when present.
   - Otherwise inspect recent `~/.codex/sessions/**/*.jsonl` files and prefer the current task or repository.
   - Keep repository and task boundaries visible when similar projects appear in the same time range.

2. **Run deterministic extraction**

   Set `SKILL_DIR` to the absolute directory containing this `SKILL.md` (use the
   path supplied by the skill loader), then invoke its bundled analyzer from any
   cwd:

   ```bash
   SKILL_DIR="/absolute/path/to/session-feedback-audit"
   python3 "$SKILL_DIR/scripts/analyze_session_feedback_jsonl.py" \
     --recent 7d \
     --format markdown \
     --out /tmp/session-feedback-audit.md
   ```

   For explicit inputs:

   ```bash
   python3 "$SKILL_DIR/scripts/analyze_session_feedback_jsonl.py" \
     /path/to/session.jsonl /path/to/other-dir \
     --format markdown \
     --out /tmp/session-feedback-audit.md
   ```

   The built-in pattern packs cover Korean and English. For another language or domain, pass a JSON object whose keys are categories and whose values are phrase arrays:

   ```json
   {
     "scope_correction": ["そうではなく"],
     "direct_action": ["実行してください"]
   }
   ```

   ```bash
   python3 "$SKILL_DIR/scripts/analyze_session_feedback_jsonl.py" \
     /path/to/sessions \
     --patterns /path/to/patterns.ja.json \
     --output-language en
   ```

   Pattern packs are phrase matchers, not language detectors. The analyzer never
   treats Latin script as proof of English. Custom packs can classify any Unicode
   text, while generated rule prose currently supports English and Korean. `auto`
   deterministically defaults to English instead of guessing from phrase hits; set
   `--output-language ko` explicitly for Korean output.

3. **Read the report as evidence**
   - Treat snippets and counts as leads, not conclusions or full conversational context.
   - Check representative snippets, counterexamples, and source context before turning a detected category into a rule.
   - By default, generate a durable rule only when a category occurs at least twice across at least two distinct JSONL files. A repeated phrase inside one file remains a candidate pattern.
   - Override the evidence floor only deliberately with `--min-occurrences` and `--min-files`; these thresholds are local operational safeguards, not a universal research standard.
   - Preserve exact repository, tool, command, and runtime names.
   - Distinguish a repeated preference from a one-off correction.

4. **Write reusable guidance**
   - Convert repeated corrections into short imperative rules.
   - Prefer a concrete “next time, do X” rule over blame or generic advice.
   - Include counts and two to five representative snippets for material findings.
   - Keep language-specific phrasing in the generated output, not in the skill's core responsibility.

5. **Apply only to safe targets**
   - Patch a prompt, skill, or local guidance file only when the user asks to apply the findings.
   - If the user asks to update Codex memory, create an ad-hoc memory note rather than editing memory files directly.
   - Otherwise return the report path and proposed rules.

## Pattern categories

Built-in packs currently cover:

- `scope_correction`
- `direct_action`
- `repo_boundary`
- `artifact_link`
- `runtime_environment`
- `language_polish`
- `avoid_confirmation`

Custom packs may extend these categories or add evidence-only categories. A category without a built-in rule template still appears in counts and snippets.

## Output

```markdown
## Session feedback summary

### Repeated patterns
- <category>: <occurrence count and distinct-file count>

### Candidate patterns
- <category>: <insufficient cross-file evidence>

### Anti-repeat rules
1. <short imperative rule>

### Evidence
- Report: <path>
- Main JSONL files: <paths>

### Verification gaps
- <missing context, unsupported output language, or none>
```

## Evidence model

- Unicode distinguishes scripts from languages: Latin is used by hundreds or thousands of languages, and one language may use multiple scripts. Do not infer English from `[A-Za-z]` or a locale from script alone.
  - https://www.unicode.org/reports/tr24/
- W3C recommends explicit language metadata for language-specific processing; heuristic detection is not a substitute for declared language.
  - https://www.w3.org/International/questions/qa-lang-why
- UK government qualitative-evaluation guidance emphasizes transparent category construction, retained source context, negative cases, and traceable links from data to conclusions. Counts support review but do not establish a durable rule by themselves.
  - https://www.gov.uk/government/publications/the-magenta-book
