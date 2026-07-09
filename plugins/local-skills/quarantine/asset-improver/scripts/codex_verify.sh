#!/usr/bin/env bash
# codex_verify.sh — cross-MODEL verification of a proposed/applied change via Codex.
# Usage: codex_verify.sh <A|B> <repo> <diff-file> <intent> <skill|hook|script>
#   A = pre-apply gate on the candidate diff (before human approval)
#   B = post-apply confirm on the committed diff
# Prints the strict-JSON verdict to stdout. Exit 0 = GO, 1 = NO-GO / fail-closed.
# FAIL-CLOSED: codex missing, error, timeout, or unparseable verdict => NO-GO.
set -uo pipefail

PASS="${1:?A or B}"; REPO="${2:?repo}"; DIFF="${3:?diff file}"; INTENT="${4:?intent}"; ATYPE="${5:?artifact type}"

nogo() { printf '{"verdict":"NO-GO","one_line_reason":"%s"}\n' "$1"; exit 1; }

command -v codex >/dev/null 2>&1 || nogo "codex CLI not available (fail-closed)"
[ -f "$DIFF" ] || nogo "diff file not found: $DIFF"

if [ "$PASS" = "A" ]; then
  TASK='A skill/hook/script change is PROPOSED (not yet applied). Decide, conservatively, whether to apply it.'
else
  TASK='A change has been APPLIED and committed. Verify the applied diff equals the stated intent and introduces no new side-effect.'
fi

PROMPT=$(cat <<EOF
You are an adversarial reviewer. $TASK
ARTIFACT_TYPE: $ATYPE
INTENT: $INTENT
DIFF:
$(cat "$DIFF")

Output STRICT JSON ONLY (no prose), exactly this shape:
{"verdict":"GO"|"NO-GO","is_real_improvement":true|false,"regressions":[],"side_effects":[],"false_block_risk":true|false,"unverified":[],"one_line_reason":"<=120 chars"}
Rules: NO-GO if ANY regression, ANY side_effect not entailed by INTENT, false_block_risk=true, is_real_improvement=false, or if you are uncertain. Silence/uncertainty => NO-GO.
EOF
)

# Read-only sandbox: codex cannot mutate the tree. Bound the run portably (macOS lacks `timeout`).
TO=""
if   command -v timeout  >/dev/null 2>&1; then TO="timeout 240"
elif command -v gtimeout >/dev/null 2>&1; then TO="gtimeout 240"; fi
# shellcheck disable=SC2086
RAW=$(printf '%s' "$PROMPT" | $TO codex exec -C "$REPO" -s read-only --skip-git-repo-check - 2>/dev/null) \
  || nogo "codex exec failed or timed out (fail-closed)"

# Extract the last JSON object containing a "verdict" key.
VERDICT_JSON=$(printf '%s' "$RAW" | python3 -c '
import sys, json, re
txt = sys.stdin.read()
best = None
for m in re.finditer(r"\{[^{}]*\"verdict\"[^{}]*\}", txt):
    try:
        obj = json.loads(m.group(0)); best = obj
    except Exception:
        pass
if best is None:
    sys.exit(2)
print(json.dumps(best))
' 2>/dev/null) || nogo "no parseable verdict in codex output (fail-closed)"

printf '%s\n' "$VERDICT_JSON"
printf '%s' "$VERDICT_JSON" | grep -q '"verdict": *"GO"' && exit 0
exit 1
