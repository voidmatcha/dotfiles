# Handover pattern notes

Use this only when the user asks why the handover workflow exists or asks to compare it with compact/resume.

## Source-backed principles

- Codex documents that long threads may be automatically compacted by summarizing relevant information and discarding less relevant details; `/compact` is intended to summarize visible conversation to free tokens. That makes compact useful but inherently lossy.
  - Sources: OpenAI Codex manual, "Context" and CLI `/compact` sections (`/codex/prompting`, `/codex/cli`).
- Codex also has native continuity paths: CLI `resume` keeps the original transcript/plan/approvals, cloud tasks can remember local conversation context, and Codex app Worktree Handoff moves a thread/code between Local and Worktree via Git operations.
  - Sources: OpenAI Codex manual, "Resuming conversations", IDE cloud tasks, and Worktrees/Handoff sections.
- OpenAI Agents SDK models handoffs as delegation to another agent; structured handoff input can be validated with Pydantic, and sessions/tracing preserve conversation continuity in framework-owned workflows.
  - Source: OpenAI Agents SDK docs (`docs/handoffs.md`, `docs/sessions`).
- Claude Code session docs expose `--continue`, `--resume`, `/clear`, `/compact`, and `/context`; Anthropic guidance frames compact as lossy summarization and recommends fresh scoped sessions or subagents when stale context would hurt.
  - Sources: `https://code.claude.com/docs/en/sessions`, `https://claude.com/blog/using-claude-code-session-management-and-1m-context`.
- Prompt-cache health is a separate decision from handoff: `/clear` when old context can be dropped, `/compact` when context should be retained with one cache rebuild; avoid changing model/tools/thinking configuration mid-session because that breaks cache sharing.
- Production-style multi-agent handoff guidance converges on: versioned schema, idempotency/trace key, explicit completed vs remaining work, decision provenance, side-effect/evidence manifest, failure-mode declaration, durable state store, and ACK/retry semantics.
  - Corroborating searches: OpenAI Agents SDK handoff docs, LangChain context-management writing on filesystem offloading + summary + recoverability tests, and public multi-agent handoff articles/tools.

## Practical rule

A handover beats compact only if it preserves recoverability better than a summary. That means the receiver gets:

1. a short structured brief;
2. file paths to original artifacts/evidence;
3. git/workspace state;
4. explicit next action and definition of done;
5. a handshake proving the receiver read and accepted it.

If any of those are missing, it is just compact with extra ceremony.

## Token / time efficiency rule

Handover is not automatically cheaper than compact.

Cache is the main reason. A same-session prompt cache can make continued work much cheaper than launching a fresh target. A handover target may have to pay cold-cache or cache-rebuild cost unless the handoff brief is tiny and durable artifacts let it avoid rereading the old transcript.

Usually cheaper:

- switching tools or tabs anyway (`omx` -> `claude`, current cmux surface must close);
- prior transcript is noisy/poisoned and only a small structured brief matters;
- original evidence is already durable as files/logs/diffs, so the receiver can inspect only what it needs;
- multiple receivers need the same package without duplicating a long transcript.

Usually more expensive:

- the current session still has a warm prompt cache and the next work is in the same tool/model/tooling configuration;
- same tool and same task can continue with `/compact` or native `resume`;
- the receiver must reread many large files because the handoff brief lacks precise artifact pointers;
- the source uses verbose summaries or launches multiple agents that all inspect the same code;
- the handoff is used repeatedly for tiny tasks where launch/handshake overhead dominates.

Cache rule of thumb:

- **Warm cache + useful context**: stay in the session; compact only if context pressure is real.
- **Expired cache + disposable context**: `/clear` is usually cheapest.
- **Expired cache + useful context**: `/compact` is usually cheaper than cross-tool handover if the same tool can continue.
- **Expired/stale cache + poisoned/noisy context or tool/tab switch required**: handover can win, but only with a concise brief and exact artifact pointers.

Efficiency target for this skill:

- default to `fast` handshake (`OFFER -> READY`) for routine handovers;
- use `verified` only when the extra ACK/CONFIRM roundtrip buys real safety;
- keep `handoff.md` short and make it point to artifacts instead of copying long logs;
- use unique run ids and target titles so concurrent handovers are easy to distinguish.
