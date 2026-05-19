---
description: Sequential multi-agent workflow for complex tasks. /orchestrate <workflow> <task>
---

# /orchestrate

Run a named workflow that chains specialized subagents with explicit handoff
contracts. Pass the workflow type and a one-line task description.

Usage: `/orchestrate <workflow> <task description>`

If `<workflow>` is omitted, pick the closest match yourself based on the
task description and announce the choice in one sentence before starting.

## Workflows

### feature — implement something new

```
brainstorming (skill)
  → comprehensive-review:architect-review        [design check]
  → executor (you, with TDD discipline)
  → tdd-workflows:tdd-orchestrator               [test coverage]
  → comprehensive-review:code-reviewer           [quality gate]
```

Stop after any step that hard-rejects (returns a verdict of "REJECT" or
"BLOCKED"). Surface the reason to the user and ask for direction.

### bugfix — find and fix a bug

```
error-debugging:error-detective                  [reproduce + classify]
  → error-debugging:debugger                     [root cause]
  → executor (you) — write failing test first
  → tdd-workflows:tdd-cycle                      [red → green → refactor]
  → comprehensive-review:code-reviewer           [regression check]
```

Skip the test-first step only if the bug is unreachable from tests (e.g.,
a TypeScript compile error). Always justify the skip in your handoff.

### refactor — restructure without behavior change

```
comprehensive-review:architect-review            [find the seams]
  → superpowers:writing-plans                    [stepwise plan]
  → executor (you) — one step at a time
  → comprehensive-review:full-review             [behavior preservation]
```

After every step, run the existing test suite. If any test changes
expected behavior, the refactor escaped its boundaries — stop.

### security — vulnerability triage or hardening

```
security-scanning:security-sast                  [scan first]
  → comprehensive-review:security-auditor        [threat-model]
  → executor (you) — minimal patch, no scope creep
  → security-scanning:security-hardening         [verify defense-in-depth]
```

For dependent vulnerabilities (CVE in transitive dep), surface to the
user before patching — they may want to wait for an upstream fix.

## Handoff contract

Between each step write a single markdown block — this is the SOLE input
to the next agent. Be ruthless about what's in it; the next agent has no
other context.

```markdown
## HANDOFF: <from> → <to>

**Goal**: <one sentence — what the next agent needs to accomplish>

**Inputs**:
- <file:line — what to read first>
- <file:line — what to read second>
- <constraint or assumption inherited from previous step>

**Output expected**:
- <concrete artifact — file path, decision, verdict, code change>

**Out of scope**: <what NOT to do — keeps agents from drifting>
```

If the next agent comes back with output that doesn't fit the contract,
that's a failure of the handoff, not the agent — fix the contract and
re-dispatch.

## Stopping rules

1. Any step's agent returns BLOCKED or REJECT: stop, surface to user.
2. Any step requires user data not in the original task description: stop,
   ask for it.
3. A step takes longer than expected for its category (>3 tool calls for a
   review agent, >10 for an executor): pause and report progress.
4. Three consecutive steps all surface the same issue: the workflow itself
   is wrong for the task — re-pick the workflow.

## What this command is NOT

- Not a magic "do everything" button. Each step is a real subagent call
  with real cost.
- Not a substitute for thinking. Pick the workflow deliberately; the
  default match is a starting point, not a verdict.
- Not appropriate for trivial tasks. If the task is a one-liner, just do
  it — orchestration overhead dwarfs the work.
