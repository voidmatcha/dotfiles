---
name: premortem
description: "Use when about to commit to a plan, rollout, migration, release, hire, or any decision that is costly or hard to reverse — run this before you start, not after. Triggers: 'premortem this', 'what could kill this', 'stress test this plan', 'what am I missing', 'poke holes in this', 'where will this break', '실패 시나리오', '뭐가 잘못될 수 있어', '이 계획 망할 이유'."
license: MIT
metadata:
  dotfiles.provenance.upstream: https://hbr.org/2007/09/performing-a-project-premortem
  dotfiles.provenance.mode: inspired-by
---

# Premortem

Imagine the plan has already failed, then work backward to list why — before you commit. Asking "what could go wrong?" gets hedged answers; assuming failure already happened triggers "prospective hindsight" and surfaces specific, honest failure modes. It is a safety belt before action, not a postmortem after.

Provenance: Mode: inspired-by; Upstream: https://hbr.org/2007/09/performing-a-project-premortem; License: MIT for this local skill text. Technique: premortem / prospective hindsight (Gary Klein, *Harvard Business Review*, 2007; popularized by Daniel Kahneman). No upstream code or article text was copied.

Local override: an optional `premortem.local.md` beside this file (gitignored, see plugins/local-skills/CONVENTIONS.md) may add machine-specific checks but must not weaken the honesty or scoring steps.

## When to use

- Costly or hard-to-reverse commitments: launches, deploys, migrations, CI/CD or install changes that run on every machine, schema/data migrations, architecture pivots, hires, deals.
- A plan you (or an AI) already feel good about — premortem counters optimism and agreement bias.

When NOT to use:

- No concrete plan yet — help plan first, then premortem.
- A question with one right answer — just answer it.
- Feedback on a draft — that is editing, not premortem.
- A decision already made and irreversible — nothing left to change.

## Workflow

1. **Gather the plan.** Restate the concrete plan, the commitment, and what "success" looks like. If it is vague, get the minimum specifics first — vague input yields vague failure modes.
2. **Assume total failure.** Frame it: "It is [horizon] later and this failed badly. We are not asking *if* — we are explaining *why*."
3. **Enumerate failure modes.** List specific, concrete reasons it failed. Push past the obvious to the honest, uncomfortable ones: false assumptions, dependencies, ownership gaps, edge cases, missing rollback, external changes.
4. **Score each** by likelihood (low/med/high) and impact (low/med/high); sort by the combination.
5. **Mitigate the top ones.** For each high-likelihood or high-impact mode, name a concrete committed action or an early-warning signal, and fold it back into the plan.
6. **Decide.** Output a revised plan with blind spots exposed, or an explicit proceed / adjust / don't-do call.

## Output shape

- **Failure modes** — table: cause · likelihood · impact · mitigation or early-warning signal.
- **Revised plan / decision** — the concrete changes, or a go / no-go.

Keep every item specific to this plan. Generic risks ("it might be slow") help nobody — tie each failure mode to this commitment.
