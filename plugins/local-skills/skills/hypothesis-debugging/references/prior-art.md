# Prior art and rationale

Use this only when editing or reviewing the skill. Normal debugging tasks should not need this file.

## Patterns worth preserving

- **Falsifiable hypothesis before tools.** Public hypothesis-driven debugging writeups and Zeller's scientific debugging model all stress stating a prediction before probing; evidence should be able to reject the hypothesis, not only confirm it.
- **One variable per experiment.** Debugging-rules literature repeatedly warns against shotgun fixes; one test should discriminate one candidate.
- **Good-vs-bad comparison.** Nearest known-good runs, commits, inputs, devices, and environments reduce the search space faster than broad inspection.
- **Attempt log / audit trail.** Zeller and Debugging Rules both recommend recording hypotheses, experiments, and outcomes so failed predictions are not accidentally reused.
- **Bias reset.** Cognitive-bias debugging sources call out anchoring, confirmation bias, availability, premature closure, and sunk cost; loaded skills/docs and the last similar incident can become anchors.
- **Fresh view threshold.** If quick debugging exceeds a short timebox or three attempts fail, rebuilding the candidate table is better than strengthening the same mitigation.
- **Quick five-whys before the formal table.** For shallow bugs, an iterative "why" causal chain reaches a testable root fast; escalate to the candidate table once it branches, stalls, repeats a vague cause, or the timebox passes. Borrowed from Five Whys / incident RCA practice.
- **Original failure verification.** A fix is not proven by unrelated improvement; verify the original reproduction path and the smallest regression check.

## Public sources checked

- akuszyk.com, "Hypothesis-driven debugging" (2024): falsifiable hypotheses and telemetry-driven narrowing.
- Grinnell CSC 151, "Hypothesis-driven debugging": observe, hypothesize, predict, test, reflect.
- Andreas Zeller, *Why Programs Fail* / Scientific Debugging: logbook, predictions, refine/reject hypotheses, timebox quick-and-dirty debugging.
- UNSW Debugging docs, "Change One Thing at a Time": isolate variables.
- David J. Agans, *Debugging: The 9 Indispensable Rules*: understand system, make it fail, divide and conquer, change one thing, keep audit trail, get fresh view, verify fix.
- Communications of the ACM, "Cognitive Biases in Software Development" and related traceability article: anchoring/fixation, confirmation, availability, overconfidence, and traceability as bias mitigation.
- obra/superpowers `systematic-debugging` skill: root-cause-first workflow, minimal tests, three-failed-fixes escalation, no bundled fixes.
- Five Whys (Sakichi Toyoda / Toyota Production System) and incident-response RCA writeups (Ishikawa/fishbone, five-whys): quick causal-chain entry for shallow faults before a formal hypothesis table.

## Deliberately not included

- Domain-specific axes beyond examples. Keep those in domain skills such as WebView, backend, data, infra, or test-debugger skills.
- Mandatory long-form incident template. The skill should stay usable for ordinary bugs; detailed postmortems belong elsewhere.
- Scripts. This workflow is judgment-heavy and should remain text-guided unless a specific repeatable parser/probe emerges.
