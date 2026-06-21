---
name: agent-usage-audit
description: "Audit installed Claude/Codex agents, skills, commands, recent session usage, and source-level token pressure to decide what to prune, keep, or route."
---

# Agent Usage Audit

Prefer deterministic local audit scripts. Do not paste transcript contents, prompts,
raw command output, private paths, or project text.

## Workflows

### Install/usage inventory

```bash
python3 scripts/agent_usage_audit.py
```

Use this to separate installed local assets, recent usage signals, and gaps where an
install exists but usage is absent or unproven. Counts are references, not successful
outcomes.

### Source-level token pressure

```bash
python3 scripts/agent_usage_audit.py session-report --since 7d --format markdown --redact
```

Use this when deciding where token pressure is coming from across RTK, Claude local
logs, and Codex local logs. The report separates exact counters from estimated
tool-result pressure.

### RTK safety signals

```bash
python3 scripts/rtk_safety_report.py --since 30d
```

Use this to inspect fallback, explicit bypass, and repeat-after-compression candidate
counts. Repeat candidates are correlation only: same hashed command and cwd within the
repeat window after a high-compression event.

## Recommendation rules

- Recommend additions or removals only from observed patterns plus explicit user goals.
- Treat exact provider/local counters separately from heuristic token estimates.
- Treat RTK compression as command-output compression, not total-cost reduction.
- If data-source notes say a log is missing, report the gap instead of inferring from it.
