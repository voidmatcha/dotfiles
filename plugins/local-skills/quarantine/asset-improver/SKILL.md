---
name: asset-improver
description: "Auto-research and improve a repo's skills, hooks, and scripts: external real-world web research + internal audit + Codex cross-model verification, behind a propose then approve then apply gate with freeze-on-success and auto-revert. Use when asked to improve, audit, harden, or research-improve skills/hooks/scripts in the current repo."
---

# Asset Improver

Improve the skills / hooks / scripts of the **current repo (cwd)** one frontier item at a time, under a
strict net-positive discipline: *a change that introduces side-effects is worse than no fix.* Freeze what
works (commit), never regress it, advance the frontier.

Composes existing assets — do not reinvent them:
- **audit (skills):** `skills-janitor` (`/janitor-report`).
- **audit (hooks/scripts):** `scripts/audit_hooks.sh` (this skill).
- **external research:** the `deep-research` skill (Skill tool), for real-world examples/best-practices.
- **cross-model verify:** `scripts/codex_verify.sh` → `codex exec -C <repo> -s read-only` (the second model).
- **freeze/guard:** `scripts/freeze.sh` (commit + trailers + `.improve/frozen.json` ledger + accumulated guard).
- **safety:** `work-scope-guard` (run first), `source-provenance` (when importing an external pattern).

## The loop — ONE frontier item per iteration

```
0 scope-guard  -> 1 detect -> 2 audit -> 3 research -> 4 candidate (ONE atomic change)
  -> 5 Codex Pass A -> 6 human approve -> 7 apply+commit -> 8 tier verify
  -> 9 Codex Pass B -> FREEZE or REVERT -> 10 advance
```

0. **scope-guard.** If cwd is a company/sensitive dir, surface the `work-scope-guard` reminder before any fetch.
1. **detect.** `bash scripts/detect.sh` → TSV of targets (`type<TAB>path`) for `**/SKILL.md`, `hooks*.json`,
   `hooks/*.sh`, `scripts/*.sh`. It excludes this skill's own dir.
2. **audit.** Skills → `/janitor-report` (consume its `[severity] target: message` lines only). Hooks/scripts
   → `bash scripts/audit_hooks.sh <path>`. Collect findings; rank by severity. Pick ONE as the frontier item.
3. **research.** For the chosen finding, invoke the `deep-research` skill for real-world fixes/patterns. Routing:
   defuddle for public pages, Exa/WebSearch/context7 otherwise. **Never** transit sensitive/internal URLs through
   Jina/Exa; **never** bulk-scrape X/Reddit/LinkedIn. Keep citations.
4. **candidate.** Propose exactly ONE atomic change (smallest diff that addresses the finding), grounded in (3).
5. **Codex Pass A (pre-apply).** `bash scripts/codex_verify.sh A <repo> <diff-file> <intent> <artifact-type>`.
   It returns strict JSON; **NO-GO** blocks the apply. Fail-closed: no verdict = NO-GO.
6. **approve.** Use `AskUserQuestion` showing {finding, citations, the diff, Codex verdict}. Apply only on approval.
   A human may override a Codex NO-GO, but that override MUST be recorded in the commit trailer.
7. **apply.** Apply the one change to the working tree (do NOT commit yet).
8. **verify.** Run the **behavioral** check for the artifact type (see "Verification" below) plus the static floor
   (`scripts/tier_check.sh`), metric = delta vs the baseline captured pre-change. Static lint/parse is necessary but
   NEVER sufficient for a behaviour-affecting change. Any regression — a hook false-block, a drop in skill trigger
   accuracy, a golden-output divergence — means do not freeze.
9. **freeze, then Codex Pass B (order matters).** `scripts/freeze.sh` commits ONLY the content change (the
   `.improve/` ledger is local-only). THEN run **Codex Pass B** on the *committed* diff
   (`scripts/codex_verify.sh B ...`). NO-GO ⇒ `git revert HEAD`. (Pass B inspects the real repo state, so it must run
   AFTER the commit — running it on an uncommitted change yields a spurious NO-GO.)
10. **advance.** Re-run the accumulated guard (all frozen steps' checks). Pick the next frontier item. Stop on
    plateau (no green-able candidate) or when the user says stop.

## Keep / revert = three-key AND gate

Freeze **only if `Codex GO (Pass A + Pass B) ∧ behavioural/tier-PASS ∧ human-approve`**. Otherwise revert. Codex
NO-GO cannot be overridden by the tiers — only by a human, with a logged reason in the trailer.

## Verification — behavioural by default

A change that affects **selection, blocking, execution, output, or side-effects** MUST be verified by **executing
the artifact**, not by static checks alone. This is mandatory for: a skill `description` (it changes *triggering*),
a hook deny/allow rule, and any script behaviour. Static lint/parse is necessary but **never sufficient** for these.
Only pure prose / comments / formatting / docs-body changes may rely on static-only — and even then the freeze must
record `Behavioral-verification: static-only (NOT executed)`.

Run the behavioural check via `scripts/behavioral_check.sh <skill|hook|script> ...`, **generating the harness if
absent**. Metric = delta vs a baseline captured on the pre-change tree (run each ≥2× to absorb LLM flakiness).
This eval is a **noisy regression signal, not proof** — it depends on model version, plugin-namespace competition,
and stream-parser assumptions — so it MUST fail closed on uncertainty and keep raw tool-use names in the report.

Skill mode probes FIRST, then discriminates: `scripts/skill_probe.py` runs `claude -p` and records the *real*
tool-use target the model routes to. If the skill under test is already installed (a global plugin fires under its
own name, e.g. `local-skills:asset-improver`), it **shadows** the injected candidate description — `run_eval.py`'s
throwaway-command detection would score the genuine activation as zero and a recall delta is NOT attributable to the
description change. So skill mode returns **UNVERIFIED → human gate** (state `shadow`), recording the raw names as
evidence; it never reports a false "no activation". Only when NO installed skill of that name fires (state `clear`)
does it fall through to `skill-creator/run_eval.py`'s old-vs-new trigger discrimination — and even then, a `recall
0→0` result, **zero should-trigger=true queries** (`pos=0`, where recall is vacuous), or unparseable run_eval output
all return **UNVERIFIED**, never PASS. Never a false green from a harness that measured nothing. (`unexec` is the
probe-phase state for a claude-missing/timeout/empty run, which also resolves to UNVERIFIED.)

**Scope limit (honest).** For the realistic inner loop — improving the description of an *already-installed* skill —
the live CLI routes to that skill under its own name on every positive query, so the state is **always `shadow` ⇒
UNVERIFIED ⇒ human gate**. The automatic PASS/REVERT discrimination path is reachable only for an *uninstalled*
skill under test. So skill-mode does **not** auto-verify an installed-skill description change; that case is
human-gate by design (the eval stays honest instead of fabricating a signal). Auto-attribution would require an
isolated config-HOME where the target skill is unregistered so the candidate description is the sole carrier — a
deliberate, unbuilt residual, NOT a solved capability.

| Type | Behavioural check (actually executed) | REVERT if |
|---|---|---|
| **SKILL** | `skill_probe.py` observes the real `claude -p` routing first: if the installed skill fires under its own name (`shadow`) → UNVERIFIED (delta not attributable). Only when `clear` does `skill-creator`'s `run_eval.py` discriminate ~5 should-trigger + ~5 should-NOT prompts, old vs new description | recall drops **or** false-trigger rate rises vs baseline (clear path); installed-skill shadow or `recall 0→0` ⇒ UNVERIFIED → human gate, never PASS |
| **HOOK** | fire-matrix: actually run the hook on ≥1 should-DENY input (must block) and ≥3 should-ALLOW inputs (must NOT block) | the should-deny case stops blocking, **or** any should-allow case newly blocks (false-block) |
| **SCRIPT** | capture golden exit/stdout on representative inputs pre-change; run post-change; compare | exit/output diverges from golden |

**Static floor** (always, necessary-not-sufficient, via `scripts/tier_check.sh`): `.sh` → `shellcheck -Serror`+`bash -n`;
`.py` → `py_compile`+`ruff`; `SKILL.md`/`*.json` → frontmatter/JSON validity. Plus the repo's own tests if it has
`ci-local.sh`/`pytest`/`go test`/`npm test`. Any of these going newly-red = REVERT.

- **Cannot execute** (no harness generable, or unsafe to run): the change is `behaviorally-unverified` → it CANNOT
  auto-keep. Route to the human gate with that flag and record `Behavioral-verification: static-only (NOT executed)`
  in the trailer. **Never present a static pass as behavioural confirmation.**
- **Generated harnesses join the guard:** save the eval / fire-matrix as an artifact and add it to the accumulated
  guard so every future step re-runs it.
- **Keep harnesses honest:** baseline before/after, mixed positive+negative cases, ≥1 case derived from a real
  failure, held-out negatives borrowed from adjacent skills/hooks, and the eval LABELS reviewed by the human before
  freeze. An LLM judge may *draft* scenarios but is never itself the verification (it tests opinion, not routing). The
  generator may never declare its own harness sufficient.

## Freeze: side-effect trailer is mandatory

Each frozen step is exactly one commit (`scripts/freeze.sh`) carrying the standard trailer
(`Constraint/Rejected/Confidence/Scope-risk/Not-tested`) **plus** these required fields:

```
Behavioral-verification: <how it was EXECUTED (e.g. "trigger-eval 5/5 recall, 0 false-trigger") | "static-only (NOT executed)">
Protects-green-path: <the specific check/path this change keeps green>
Verified-unaffected: <paths/behaviors re-run and confirmed unchanged; "none-claimed" is forbidden>
```

`freeze.sh` emits `Behavioral-verification` from `AI_BEHAVIORAL` (defaulting to `static-only (NOT executed)`), and
hard-blocks an empty `Protects-green-path`/`Verified-unaffected`. A `static-only` value is allowed ONLY for the
prose/docs class above; for a behaviour-affecting change it signals the step should not have auto-frozen.

`freeze.sh` records each step in `.improve/frozen.json` and accumulates a **guard** (union of frozen tier checks).
Before any new step can freeze, the guard must still be green — a regression in a frozen artifact **vetoes and
reverts** the new step. Frozen commits are never amended or rebased; later work only adds commits.

## Notes
- Stage commits by explicit path — never `git add -A` (the target repo may have unrelated uncommitted work).
- If `codex` is unavailable, Pass A/B fail-closed (NO-GO) and the step falls to the human gate; never silent-apply.
- When a candidate imports an external pattern, run `source-provenance` (record Upstream/License/Mode).
