---
name: hypothesis-debugging
description: "Use when investigating bugs, regressions, flaky or intermittent failures, unexpected UI/runtime behavior, incidents, or a fix that didn't work — especially when the symptom and the cause aren't obviously linked, or repeated guesses keep missing. Triggers: 'debug this', 'why is this failing', 'find the root cause', 'this fix didn't work', '디버깅', '원인 찾아줘', '왜 안돼'."
---
# Hypothesis Debugging

Debug by narrowing possibilities with evidence. Do not jump from symptom to fix; first model what works, what fails, and which falsifiable candidate best explains that split.

## Output shape

Use this compact structure for non-trivial bugs:

```md
## Symptom facts
- Confirmed:
- Not confirmed:
- Works:
- Fails:
- Timeline / earliest symptom:
- Recent changes / environment differences:
- Prior frames to reset:

## Candidate causes
| Candidate | Supporting evidence | Contradicting evidence | Prediction / falsifier | Cheap test | Confidence |
| --- | --- | --- | --- | --- | --- |

## Focused hypothesis
I think [candidate] is most likely because [evidence].
Falsifier: if [observable result], this hypothesis is wrong.

## Next experiment
Run/change/inspect [one thing] to confirm or reject the hypothesis.

## Attempt log
| Attempt | Hypothesis | Test | Result | Keep / reject / refine |
| --- | --- | --- | --- | --- |

## Fix boundary
If confirmed, fix [source]. Do not stack unrelated mitigations.
```

## Quick mode (shallow bugs)

For a simple, shallow bug, first try a quick **five-whys** causal chain: state the symptom and ask "why" iteratively until you reach a root you can test. Escalate to the full candidate table below the moment the chain branches, stalls, repeats a vague cause, or quick debugging passes ~10 minutes without strong evidence.

## Workflow

1. **Freeze the symptom in observable terms.** Report symptoms before theories. Prefer concrete facts: error text, screenshots, event order, device, runtime version, branch/commit, reproduction steps.
2. **Make it fail or bound the failure.** Reproduce when possible. If not reproducible, define the narrowest observed conditions and what evidence is missing.
3. **Compare good vs bad.** Identify the nearest known-good run, environment, commit, input, user path, or component; divide the search by differences.
4. **Split into diagnostic axes.** Examples: existence, data/state freshness, geometry/layout, interaction/hit testing, rendering/output, async timing, network/API, storage/cache, environment/config, lifecycle/resume, integration boundary.
5. **List plausible candidates before choosing.** Include boring and environment candidates. Do not discard a candidate just because the first fix would be inconvenient.
6. **Reset inherited bias.** Treat prior attempted fixes, teammate theories, recently loaded skills/docs, and the last similar incident as candidate generators, not proof. Add at least one competing candidate from a different axis before focusing.
7. **Make predictions explicit.** For the focused hypothesis, write the result that would falsify it. Searching only for confirming evidence is not enough.
8. **Run the smallest discriminating experiment.** One hypothesis, one variable. Prefer read-only inspection, logs, assertions, reproduction narrowing, or temporary local probes before production code changes.
9. **Record and update.** Keep an attempt log. A refined hypothesis must explain earlier observations, keep passed predictions, and exclude failed predictions.
10. **Fix only after the cause is confirmed.** Fix the source failure. Create or preserve a failing test/probe when feasible before changing production code.
11. **Stop escalation drift.** If quick debugging takes more than about 10 minutes without strong evidence, switch to this formal table. If three attempts fail or mitigations grow broader, rebuild the candidate table and get a fresh view.
12. **Verify the original failure.** Confirm the original reproduction path now passes, the fix caused the change, and the smallest regression check covers it.

## Diagnostic axis examples

Use mismatches between axes to reduce search space:

- Object/data exists but output is missing → inspect render/output path before creation path.
- Interaction works but visual output is wrong → do not start by fixing event wiring.
- Layout box is correct but content is stale → inspect state, cache, lifecycle timing.
- Local works but CI/device/prod fails → inspect environment, version, permissions, timing, config propagation.
- Retry fixes it → inspect readiness/order/lifecycle; avoid blind sleeps unless no condition exists.

Do not encode domain-specific conclusions here. For example, web UI can split into DOM/layout/hit-test/paint/compositing, while backend flow can split into request/auth/service/database/cache. Load the relevant domain skill for domain-specific interpretation.

## Red flags

Stop and return to the candidate table when you notice:

- fix proposed before the failure path is reproduced or bounded.
- multiple changes bundled into one attempt.
- explanation only says "timing issue", "WebView bug", "cache", or "race" without a specific boundary or event order.
- evidence contradicting the favorite hypothesis is ignored.
- existing skill/doc guidance treated as confirmation instead of one input to test.
- a fix modifies a working axis instead of the failing axis.
- the same mitigation is made stronger after it already failed once.

## Completion bar

Before claiming resolution, report:

- root cause in one sentence.
- why rejected candidates are less likely.
- exact experiment or test that confirmed the cause.
- why the fix targets the source.
- verification using the original reproduction path plus the smallest regression check available.
## Maintenance reference

When editing or reviewing this skill, check [prior-art](./references/prior-art.md) for the public debugging sources behind the workflow. Do not load it during ordinary bug investigations unless the user asks for rationale.

