---
name: verify-output
description: "Use when an AI answer needs fact-checking before you trust or publish it — claims, numbers, file/command references, or causal/security statements headed into a README, PR, docs, report, or decision. Triggers: 'verify this', 'fact-check this', 'is this accurate', 'check for hallucinations', '검증해줘', '이거 맞아', '환각 확인'."
---
# Verify Output

Use this skill to audit an AI answer before trusting or publishing it. Treat the
latest assistant output as the target unless the user provides a specific text,
file, diff, report, or claim list.

Provenance: Upstream: https://github.com/yug1224/dotfiles/tree/main/packages/shared/shared/ai/commands/verify-output.md; License: MIT; Mode: inspired-by; Local changes: converted from a Claude/Cursor command into a concise Codex local skill for evidence-first claim verification. The "try to refute first" and explicit web fact-check steps are inspired by the public "doublecheck" three-layer verification pattern (extract claims -> find supporting/contradicting sources -> adversarial review); Mode: inspired-by.

## Local override

Before auditing, check for local-only instructions:

1. `plugins/local-skills/CONVENTIONS.local.md`
2. `plugins/local-skills/skills/verify-output/verify-output.local.md`

Read only files that exist. Local overrides can tighten evidence policy or add
private source rules, but must not weaken safety, privacy, or verification
requirements.

## Workflow

1. **Identify target output**
   - Use the immediately preceding assistant answer by default.
   - If the user supplied text or a path, verify that instead.
   - If the target is ambiguous, ask one short clarification question.

2. **Extract claims**
   - List concrete claims: numbers, file names, commands run, behavior changes,
     security/safety statements, causal explanations, and recommendations.
   - Ignore purely stylistic phrasing unless it changes meaning.

3. **Check evidence (try to refute first)**
   - For each claim, actively seek *disconfirming* evidence before accepting it —
     try to refute the claim, not only confirm it.
   - Prefer local evidence: command output, git diff, files, tests, metrics,
     logs, and configured docs.
   - **Web fact-check (external claims):** when a claim depends on external/public
     behavior or facts, run a bounded public search for *both* supporting and
     contradicting sources (see agent-reach), and cite source links in the report.
   - Do not route private/internal/authenticated URLs or secret-bearing content
     through hosted readers.

4. **Classify every meaningful claim**
   - `supported` — directly backed by checked evidence, and a refutation attempt failed.
   - `corrected` — direction right, but number/scope/source/wording needed fix.
   - `unsupported` — no adequate evidence found.
   - `not-checked` — verification would require missing access, destructive work,
     external production state, or user-provided artifacts.

5. **Repair the answer**
   - Remove or soften unsupported claims.
   - Add scope, date/window, and source boundaries for measured claims.
   - Keep caveats attached to the claim they limit.
   - Do not invent citations or pretend a check ran.

## Output format

```markdown
## Verification result

**Verdict**: pass | pass-with-corrections | fail | not-checked

### Claim audit

| Claim | Status | Evidence / correction |
| --- | --- | --- |
| ... | supported/corrected/unsupported/not-checked | file, command, metric, or reason |

### Corrected answer

<final revised text, or "No correction needed">

### Verification gaps

- <anything not checked and why>
```

Keep the report concise. If the user asks only for a direct corrected answer,
return the corrected answer plus a short evidence note.
