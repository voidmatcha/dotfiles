#!/usr/bin/env bash
# freeze.sh — commit one improved asset as a frozen step, with mandatory side-effect trailers,
# a frozen-set ledger, and an accumulated guard that reverts the step if any frozen artifact regressed.
# Usage: freeze.sh <repo> <target-path> <baseline.json> <protects> <verified-unaffected> <subject> [body]
# Extra standard trailers may be supplied via env: AI_CONSTRAINT AI_REJECTED AI_CONFIDENCE AI_SCOPE_RISK AI_NOT_TESTED
set -uo pipefail

REPO="${1:?repo}"; TARGET="${2:?target}"; BASELINE="${3:?baseline.json}"
# Trailer fields default to empty so the explicit checks below own the block (clear msg, exit 3).
PROTECTS="${4-}"; UNAFFECTED="${5-}"; SUBJECT="${6:?commit subject}"; BODY="${7:-}"
cd "$REPO" || exit

# --- 1. Enforce the side-effect trailers (hard block on empty / hand-waved) ---
bad() { echo "FREEZE BLOCKED: $1" >&2; exit 3; }
[ -n "${PROTECTS// }" ] || bad "Protects-green-path is empty"
[ -n "${UNAFFECTED// }" ] || bad "Verified-unaffected is empty"
printf '%s' "$UNAFFECTED" | grep -qiE '^(none|none-claimed|n/a)$' && bad "Verified-unaffected='none-claimed' is forbidden"

SELF=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LEDGER_DIR="$REPO/.improve"; LEDGER="$LEDGER_DIR/frozen.json"; BASE_DIR="$LEDGER_DIR/baselines"
mkdir -p "$BASE_DIR"
safe=$(printf '%s' "$TARGET" | tr '/.' '__')
cp "$BASELINE" "$BASE_DIR/$safe.json"

# --- 2. Commit ONLY the content change. The ledger is local-only state (git exclude),
#         so a content commit is never polluted with bookkeeping. Never `git add -A`. ---
EXCL="$REPO/.git/info/exclude"
[ -f "$EXCL" ] && ! grep -qxF '.improve/' "$EXCL" 2>/dev/null && printf '.improve/\n' >> "$EXCL"
git add -- "$TARGET" 2>/dev/null || true
git commit -q -F - <<EOF
$SUBJECT

$BODY

Constraint: ${AI_CONSTRAINT:-none}
Rejected: ${AI_REJECTED:-none}
Confidence: ${AI_CONFIDENCE:-medium}
Scope-risk: ${AI_SCOPE_RISK:-none}
Not-tested: ${AI_NOT_TESTED:-none}
Behavioral-verification: ${AI_BEHAVIORAL:-static-only (NOT executed)}
Protects-green-path: $PROTECTS
Verified-unaffected: $UNAFFECTED
EOF
COMMIT=$(git rev-parse --short HEAD)

# --- 3. Record in the frozen ledger ---
python3 - "$LEDGER" "$COMMIT" "$TARGET" "$BASE_DIR/$safe.json" "$PROTECTS" "$UNAFFECTED" <<'PY'
import json, os, sys
ledger, commit, target, baseline, protects, unaffected = sys.argv[1:7]
data = json.load(open(ledger)) if os.path.exists(ledger) else []
data.append({"commit": commit, "artifact": target, "baseline": baseline,
             "protects_path": protects, "verified_unaffected": unaffected})
json.dump(data, open(ledger, "w"), indent=2)
PY
# Ledger is local-only (git-excluded) — not committed, so the content commit stays pure.

# --- 4. Accumulated guard: every frozen artifact's tier check must still pass ---
GUARD_FAIL=""
while IFS=$'\t' read -r art base; do
  [ -f "$art" ] && [ -f "$base" ] || continue
  if ! bash "$SELF/tier_check.sh" check "$art" "$base" >/dev/null 2>&1; then
    GUARD_FAIL="$art"; break
  fi
done < <(python3 -c '
import json,sys
for e in json.load(open(sys.argv[1])):
    print(e["artifact"]+"\t"+e["baseline"])
' "$LEDGER" 2>/dev/null)

if [ -n "$GUARD_FAIL" ]; then
  echo "GUARD REGRESSION on frozen artifact: $GUARD_FAIL — reverting this step" >&2
  git revert --no-edit HEAD >/dev/null 2>&1 || git reset --hard HEAD~1 >/dev/null 2>&1
  exit 4
fi

echo "FROZEN $COMMIT  $TARGET"
