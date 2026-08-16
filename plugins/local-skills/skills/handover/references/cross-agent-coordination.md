# Cross-agent coordination

Read this when Claude, Codex, or another LLM must work across separate sessions, observe different surfaces, or cross-check each other. This is a `handover` profile, not a separate top-level skill: `handover` owns the package, target prompts, ACK/READY validation, and source-close rule.

## External grounding

Public sources checked with `agent-reach` public-only rules:

- [OpenAI Agents SDK: Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/) distinguishes LLM-driven orchestration, code-driven orchestration, agents-as-tools, handoffs, parallel agents, and structured outputs.
- [OpenAI Agents SDK: Handoffs](https://openai.github.io/openai-agents-python/handoffs/) defines handoffs as delegating work to another specialized agent and supports handoff metadata/callbacks.
- [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) describes a lead agent that decomposes work, subagents that return findings, and failure modes such as duplicate work, runaway subagents, and insufficient division of labor.
- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) names orchestrator-workers, evaluator-optimizer, routing, and parallelization as useful workflow patterns when tasks have clear boundaries and feedback loops.
- [Microsoft AutoGen: Saving and loading state](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/state.html) shows agent/team state must be explicitly saved and loaded when continuity is required across runs.

Use those sources as support for the shape of this profile, not as proof that every local backend feature already exists.

## Invariants

1. **One coordinator owns truth.** Pick one source session or shell coordinator to decide sequencing, merge results, and close the loop. Other agents submit artifacts.
2. **Exchange artifacts, not raw transcripts.** Send objective, constraints, decisions, changed files, evidence, risks, and next action. Do not paste unbounded chat logs.
3. **Bound every target role.** Give each agent one role and one output contract. Avoid letting every model re-plan the whole task.
4. **READY proves receipt.** A target is not live just because a tab exists or input was sent. It must write ACK/READY per the handover contract.
5. **Display backends do not decide.** cmux and purplemux provide visible terminals/tabs and health checks. They do not own task state.
6. **Public research stays public.** Use `agent-reach` only for public web/GitHub/community evidence. Never send company, private repo, localhost, authenticated, or secret-bearing session text to hosted readers/search tools.

## What the public sources imply locally

| Source pattern | Local rule |
| --- | --- |
| OpenAI handoffs delegate to specialized agents. | Handover targets get explicit roles and READY markers instead of a vague "continue this" prompt. |
| OpenAI code-driven orchestration is more deterministic than pure LLM routing. | A coordinator or script owns sequencing; target LLMs execute bounded units. |
| OpenAI agents-as-tools keep a manager in control; handoffs transfer conversation. | Prefer reviewer/verifier/executor targets as artifact producers unless the user explicitly wants the target to take over. |
| Anthropic lead/subagent research needs division of labor and effort budgets. | Default to one executor plus one reviewer; add more targets only when subtasks are genuinely parallel. |
| Anthropic reports duplicate work and runaway subagents without guardrails. | Each target prompt includes write scope, output schema, stop condition, and escalation path. |
| AutoGen requires explicit save/load for continuity. | Treat `.handover/artifacts/<run>/` as the durable state boundary; do not rely on a live tab label or raw chat memory. |

## Default role split

| Role | Good default owner | Output artifact |
| --- | --- | --- |
| Coordinator | Claude/Codex source session | `coordinator-status.md`, `state.jsonl`, final merge decision |
| Executor | Codex target | patch summary, commands run, test evidence, remaining risks |
| Reviewer/critic | Claude target | read-only review with ranked findings and concrete file references |
| Verifier | Codex or a separate Claude target | validation result, pass/fail evidence, reproducible commands |
| Researcher | `agent-reach` or external research target | public-source notes with URLs and assumptions |

Use fewer roles when the task is small. Two targets are often enough: one executor and one reviewer. Use more only when the coordinator can give each target a non-overlapping scope and a concrete artifact to produce.

## Workflow

1. If deciding whether to continue, compact, clear, or hand off, run `context-check` first.
2. Create one handover run directory with `handover.py init`. Include all target roles in the task/success text.
3. Launch only verified display targets. Apply `display-adapter-contract.md`, then the chosen backend reference (`cmux-display.md` or `purplemux-display.md`).
4. Send each target only its generated prompt plus its role boundary:
   - executor: write scope, tests to run, artifact to update;
   - reviewer: read-only scope, finding format, no edits;
   - verifier: exact claim to prove, smallest sufficient validation;
   - researcher: public-only query scope and citation requirement.
5. Wait for ACK/READY. If missing, inspect the display backend and repair delivery before continuing.
6. The coordinator reads target artifacts, resolves conflicts, performs final verification, and records the decision.
7. Close the source session only after `handover.py validate --run-dir <dir>` reports complete. For purplemux sources, close only an explicitly recorded workspace/tab id; otherwise leave the source open.

## Watch mode rule

Treat `watch` as polling a known run directory and known target handles, not as discovering arbitrary live sessions.

A watcher may inspect:

- `.handover/artifacts/<run>/handoff.json`
- `.handover/artifacts/<run>/targets/<target>/ready.json`
- `.handover/artifacts/<run>/coordinator-status.md`
- `.handover/artifacts/<run>/state.jsonl`
- selected backend status/result for the recorded cmux surface or purplemux tab

A watcher must not infer success from:

- a tab existing;
- a cmux/purplemux label matching old text;
- an agent producing any output;
- a live transcript containing plausible progress.

Advance only from validated artifact state. If validation fails, preserve source state and report blocked instead of closing or relaunching unrelated sessions.

## Target prompt suffixes

Append one of these to the generated target prompt when the user asks for cross-agent work.

### Executor target

```text
Role: executor. Stay inside the assigned write scope. Produce a result artifact with changed files, commands run, test evidence, and remaining risks. Escalate conflicts to the coordinator instead of re-planning the whole task.
```

### Reviewer target

```text
Role: reviewer. Do not edit files. Review the handoff package and current diff. Return ranked findings with concrete file/line references, false-positive risk, and the smallest fix that would satisfy the concern.
```

### Verifier target

```text
Role: verifier. Prove or disprove the coordinator's claim with the smallest sufficient checks. Return exact commands, outputs, pass/fail status, and any validation gap.
```

### Research target

```text
Role: researcher. Use public sources only. Do not send private repo text, localhost URLs, authenticated pages, secrets, company/client data, or raw session transcripts to hosted tools. Return URLs, evidence, assumptions, and confidence.
```

## Natural language triggers

Treat these as cross-agent coordination requests inside `handover`:

- "Claude랑 Codex 번갈아 보면서 진행"
- "서로 다른 LLM끼리 교차 검증"
- "각각 다른 세션을 보고 조율"
- "Claude는 리뷰, Codex는 구현"
- "Codex가 coordinator 하고 Claude 새 탭 열어"

## Anti-patterns

- Multiple agents all editing the same files without a coordinator-owned merge decision.
- Closing the source after creating a package but before target READY validation.
- Trusting stale cmux labels instead of probing real workspace/surface handles.
- Treating AgentWatch, `watch`, or a display tab as automatic discovery of arbitrary live sessions.
- Publishing private/company/session content through `agent-reach` or hosted web readers.

## Roadmap

These are not guaranteed current behavior; implement and test before documenting them as supported commands.

1. Add `handover.py init --coordination-profile cross-agent` to record roles in `handoff.json` and append the target prompt suffixes automatically.
2. Add `--target-role claude:reviewer --target-role codex:executor` parsing so natural-language role splits become deterministic target metadata.
3. Add a run-directory watcher that polls only recorded targets and artifact markers, never arbitrary live sessions.
4. Add schema validation for `coordinator-status.md`, `state.jsonl`, and target result artifacts before the coordinator advances.
5. Add a small parallelism budget: one agent for simple fact-finding or direct edits, two targets for executor/reviewer splits, more only with explicit non-overlapping scopes.
6. Add optional state export/import for cross-run continuity, but keep raw transcript export out of the default path.
