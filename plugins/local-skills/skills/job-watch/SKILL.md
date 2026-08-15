---
name: job-watch
description: Use when refreshing tracked job postings, checking whether a posting is still open, registering a new posting into the vault, or looking for new openings at target companies. Triggers include "채용 공고 갱신", "공고 아직 열려있나", "새 공고 찾아줘", "이 공고 등록해줘", "job posting check", and "구직 현황 업데이트".
---

# job-watch

Refreshes the job postings held in the llmwiki vault. There are three jobs to do,
and **they are different in kind.**

| Task | Kind | How |
| --- | --- | --- |
| Status refresh | Deterministic | Script |
| Registering a posting | Semi-deterministic | Script + a human gap analysis |
| Finding new postings | Requires judgement | Research, then **a human approves** |

The data model lives in the vault, in [[2026-08-15-archive-schema]].

## 1. Status refresh

```bash
python3 ~/dotfiles/plugins/local-skills/skills/job-watch/scripts/check.py --dry-run
```

Run `--dry-run` first to see what would change, and once you have checked it, drop
the flag and run again. `--only <slug>` narrows the target set.

What the script does:

- 404/410 → `status: closed` plus `closed_reason`
- Body changed → **appends a new snapshot** at `library/jobs/<slug>/<date>.md`
  (it does not overwrite)
- No change → refreshes `checked`
- **Timeout, 403, or a failed fetch → the note is left untouched.** Only a log line
  is emitted
- Missing required frontmatter keys are reported in the same pass (`llmwiki lint`
  does not inspect `jobs/`)

**The script never touches `fit`, the gap analysis in the body, or any `status`
other than `closed`.** The machine refreshes facts; the human makes the calls.

When something comes back changed or closed, revisit that note's gap analysis and
`fit`. The requirements may have been raised, or the visa language may have been
dropped. A `diff` between two snapshots shows exactly what moved.

### A snapshot is not finished until it is translated

Any posting that reports `first` or `CHANGED` **gets a Korean translation written
alongside it.** Collecting without translating just piles up English source text
that nobody reads.

```
library/jobs/<posting>/<date>.md        original (leave it alone)
library/jobs/<posting>/ko/<date>.md     translation
```

The viewer appends the translation below the original automatically. **Mixing the
translation into the original file makes every subsequent run report 'changed'.**

Translation policy:

- Skip the company marketing blurb; keep only **the role, the work, the
  requirements, and the terms**
- Preserve whatever the original emphasises (`Globally remote role`, years of
  experience, visa conditions)
- Put application caveats in their own section (for example, a clause
  disqualifying applicants who use AI-generated content)
- Note anything odd about the original (for example, a posting with subheadings
  from a different role mixed in)

### LinkedIn is skipped

The script does not handle `source_kind: linkedin`. Automated polling risks an
account suspension, and losing your account mid-search costs you not a list of
postings but your entire professional network. Check those by hand in your own
session, at human speed, and register them manually.

## 2. Registering a posting

Given a URL:

1. Fetch the original with `defuddle parse <url> --md` and save it to
   `library/jobs/<slug>/<today>.md`
2. Create `jobs/<slug>.md`. The schema is below
3. Create `companies/<company>.md` too if it does not exist yet
4. **Compare against `records/역량 기록.md` and write a three-line gap analysis in
   the body**
5. **If the posting is in English, write the translation to
   `library/jobs/<posting>/ko/<date>.md`**

```yaml
type: job
title: Company — Role
company: <slug from companies/>
role:
status: watching        # watching | applying | applied | closed | rejected | offer
track: remote           # remote | relocation
location:
remote_geo: worldwide   # worldwide | US | TH; SG | unknown | "-"
visa: n/a               # sponsored | none | unknown | n/a
source:
source_kind: career-page   # career-page | board | linkedin | newsletter | referral
posted: ""
deadline: ""
checked: <today>
fit: 3                  # 1~5
created / updated
```

**`remote_geo` is the gate.** "Remote" is not one thing. `Remote (US)` and
`Remote / Remote` are entirely different postings. Copy the region list exactly as
the posting states it.

Write the gap analysis in this shape:

```markdown
## 갭
- 충족: (what the capability record already covers that the requirements ask for)
- 부족: (what is missing. Be honest)
- 메울 방법: (separate what is closable from what is not) → fit N
```

Because the reasoning behind the `fit` score stays in the note, you never have to
recompute it later.

## 3. Finding new postings

Sweep the careers pages of everything in `companies/` with `status: target`. Use
`defuddle` for public pages, and route anything else through the `agent-reach`
skill.

### Enumerate exhaustively through the public ATS APIs

**Opening company careers pages one at a time is the last resort.** Most of them
render in JS, so `defuddle` cannot read them, and you end up registering only the
one posting that caught your eye while missing the other levels at the same
company. At one company only 2 of 8 postings had been registered, and one of the
missing ones carried information that inverted the level structure.

```bash
# Greenhouse — full list / individual body
curl -s "https://boards-api.greenhouse.io/v1/boards/<board>/jobs"
curl -s "https://boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>"   # HTML in .content
# Lever — the full list already includes the body
curl -s "https://api.lever.co/v0/postings/<board>?mode=json"
# Ashby
curl -s "https://api.ashbyhq.com/posting-api/job-board/<org>"
```

No authentication is needed and there is no account risk. Lift the `board` token
from the `source:` URL of an existing note.

**The target company list and the per-company measurements belong to the vault** —
see [[2026-08-17-source-api-survey]] in the vault. This skill lives in a public
repository, and which companies you are watching reveals the state of your job
search itself, so it does not get written down here. That note also records which
of the large domestic companies expose public JSON and which are SPAs that require
`agent-browser`.

If a company's careers site falls under work-scope (an internal domain), **hosted
readers are forbidden**; use local tooling only. Follow the work-scope rules of the
`agent-reach` skill exactly.

**Always pull these out during an exhaustive sweep**:

- **Years of experience required** — this differs per level even within one
  company. Scan the body with `\d+\+?\s*years?`
- **Do not assume the level ordering** — there really are companies where Lead sits
  above Staff. Sorting by convention gets it wrong
- Visa and sponsorship language. Phrasings like `Remote, United Kingdom` often mean
  **someone who already has the right to work**, not sponsorship

**Do not auto-register what the sweep finds.** Present candidates only, and let a
human choose. Irrelevant postings accumulating turns `jobs/` into a dumping ground,
and once that happens the "확인 필요" view stops meaning anything.

For a company you rule out, record `status: ruled-out` and the reason in
`companies/<slug>.md`. **This is what stops you researching the same company
twice.**

## Review happens in Bases

The views in `bases/jobs.base`:

- **확인 필요** — `checked` older than 14 days. Pick your refresh targets here
- 관찰 중 / 지원 예정 / 지원함 / 전체

## Common mistakes

| Mistake | Consequence |
| --- | --- |
| Treating a network failure as a closure | A live posting is recorded as dead. The script already blocks this, but stay alert when judging by hand |
| Recording `remote: yes/no` | The region disappears and the filter becomes meaningless. Put the list in `remote_geo` |
| Overwriting a snapshot | You lose when and how the requirements changed. Stack them as dated files |
| Registering sweep results directly | The "확인 필요" view fills up with noise |
| Letting the script update `fit` | Judgement passes into the machine's hands. Refresh facts only |
| Collecting but deferring the translation | English source text piles up and nobody reads it |
| Closing on a single 404 | A transient error kills a live posting. The script confirms the HTTP status independently, and the same applies when judging by hand |
