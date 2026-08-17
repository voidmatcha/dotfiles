#!/usr/bin/env bash
# behavioral_check.sh — EXECUTE the artifact and compare behaviour vs baseline (not static lint).
# Modes:
#   skill  <skill-dir> <eval-set.json> <old-desc-file> <new-desc-file>
#       FIRST probes real `claude -p` routing (skill_probe.py): if the installed skill fires under its own
#       name it SHADOWS the candidate description -> UNVERIFIED (delta not attributable). Only when
#       un-shadowed does skill-creator's run_eval.py discriminate the OLD vs NEW description; PASS iff
#       recall does not drop AND false-trigger does not rise.
#   hook   <hook-cmd-template> <fire-matrix.json>
#       Fire-matrix: feeds each input to the hook; should-deny must block, should-allow must NOT block.
#   script <script-cmd> <golden.json>
#       Golden: runs each case, compares exit code + stdout substring.
# Prints a JSON verdict; exit 0 = PASS, 1 = REVERT, 2 = UNVERIFIED (could-not-execute, shadowed by the
# installed skill, or vacuous measurement => behaviorally-unverified, route to human gate).
set -uo pipefail

MODE="${1:?skill|hook|script}"; shift
RUN_EVAL="${RUN_EVAL:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/skill-creator/scripts/run_eval.py}"
verdict() { printf '{"verdict":"%s","detail":%s}\n' "$1" "${2:-null}"; }

case "$MODE" in
  skill)
    SKILL_DIR="${1:?skill dir}"; EVALSET="${2:?eval-set.json}"; OLDF="${3:?old desc file}"; NEWF="${4:?new desc file}"
    [ -f "$RUN_EVAL" ] || { verdict UNVERIFIED '"run_eval.py not found"'; exit 2; }
    [ -f "$EVALSET" ] && [ -f "$SKILL_DIR/SKILL.md" ] || { verdict UNVERIFIED '"missing eval-set or SKILL.md"'; exit 2; }
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROBE="$SCRIPT_DIR/skill_probe.py"

    # --- Step 1: real-activation probe (fail-closed honesty) ----------------
    # run_eval.py only detects ITS OWN throwaway command name. When the skill under
    # test is already installed (e.g. a global plugin), the model invokes the REAL
    # skill under its real name, which run_eval scores as a non-trigger -> recall
    # floors at 0 for BOTH descriptions and the injected --description has no causal
    # effect on selection. So before trusting any recall delta, OBSERVE what claude
    # actually routes to. No file is mutated; raw tool-use names are recorded.
    SKILL_NAME="$(awk -F': *' '/^name:/{gsub(/[\r"]/,"",$2); print $2; exit}' "$SKILL_DIR/SKILL.md")"
    # Default FAIL-CLOSED: if we cannot even run the probe (no parseable skill name
    # or the probe script is missing), we cannot rule out a shadow -> unexec, never clear.
    SHADOW_JSON='{"state":"unexec","raw_tools":[],"reason":"probe not run (no skill name or skill_probe.py missing)"}'
    if [ -n "$SKILL_NAME" ] && [ -f "$PROBE" ]; then
      QF="$(mktemp)"; trap 'rm -f "$QF"' EXIT
      # Probe EVERY query (positive AND negative): the installed skill shadows the
      # discrimination if it activates on ANY prompt — including over-triggering on a
      # negative, which run_eval's throwaway would otherwise mis-measure as clean.
      python3 -c 'import json,sys; ev=json.load(open(sys.argv[1])); print(json.dumps([q["query"] for q in ev]))' "$EVALSET" > "$QF"
      PROBE_OUT="$(python3 "$PROBE" --queries-file "$QF" --target-skill "$SKILL_NAME" --skill-dir "$SKILL_DIR" --runs 1 --timeout 45 2>/dev/null)"; PROBE_RC=$?
      SHADOW_JSON="$(PROBE_RC="$PROBE_RC" python3 - "$PROBE_OUT" <<'PY'
import json, os, sys
rc = os.environ.get("PROBE_RC", "0")
raw = sys.argv[1] if len(sys.argv) > 1 else ""
try: data = json.loads(raw)
except Exception: data = None
if not isinstance(data, dict) or "probes" not in data:
    print(json.dumps({"state": "unexec", "raw_tools": [], "reason": "probe output unparseable"})); sys.exit(0)
# skill_probe.py already decided whether the TARGET skill routed (matching the
# Skill name OR a Read of its SKILL.md, scanning the whole run, not just the first
# tool). We aggregate its per-run verdict, fail closed on any could-not-measure run,
# and ALWAYS collect raw tool names (evidence contract holds even on unexec).
# Precedence: shadow > unexec > clear, so a partial timeout is NEVER read as "clear".
fired, errored, raw_tools = 0, 0, []
for p in data["probes"]:
    for r in p.get("runs", []):
        if r.get("target_fired"):
            fired += 1
        if r.get("error"):
            errored += 1
        for t in r.get("tools", []):
            raw_tools.append({"query": p["query"][:60], "tool": t.get("tool"), "target": t.get("target", "")})
# rc==2 (skill_probe: claude missing or EVERY run errored) forces unexec even if no
# per-run error flag was set; raw_tools observed before erroring are still reported.
state = "shadow" if fired else ("unexec" if (errored or rc == "2") else "clear")
print(json.dumps({"state": state, "real_hits": fired, "errored_runs": errored, "raw_tools": raw_tools}))
PY
)"
    fi
    # Any failure to parse the probe state fails CLOSED to unexec (never clear/PASS).
    STATE="$(printf '%s' "$SHADOW_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state","unexec"))' 2>/dev/null || echo unexec)"

    if [ "$STATE" = "unexec" ]; then
      printf '{"verdict":"UNVERIFIED","detail":{"reason":"real-activation probe could not execute (claude missing/timeout/empty stream) -> behaviorally-unverified, human gate","probe":%s}}\n' "$SHADOW_JSON"
      exit 2
    fi
    if [ "$STATE" = "shadow" ]; then
      printf '{"verdict":"UNVERIFIED","detail":{"reason":"installed skill %s fired under its real name, shadowing the injected candidate description: a recall delta is NOT attributable to the description change in-context -> route to human gate (raw tool-use names recorded)","skill":"%s","probe":%s}}\n' "$SKILL_NAME" "$SKILL_NAME" "$SHADOW_JSON"
      exit 2
    fi

    # --- Step 2: throwaway-command discrimination (valid ONLY when un-shadowed) ---
    # No installed skill named "$SKILL_NAME" fired, so run_eval's throwaway command
    # is the carrier of the candidate description and its old-vs-new delta is real.
    # run_eval.py does `from scripts.utils import ...`, so its parent must be importable.
    CREATOR_ROOT="$(dirname "$(dirname "$RUN_EVAL")")"
    run_one() { # description-file -> run_eval JSON on stdout
      PYTHONPATH="$CREATOR_ROOT" python3 "$RUN_EVAL" --eval-set "$EVALSET" --skill-path "$SKILL_DIR" \
        --description "$(cat "$1")" --runs-per-query 2 --num-workers 6 --timeout 45 2>/dev/null
    }
    OLD_OUT=$(run_one "$OLDF") || { verdict UNVERIFIED '"run_eval failed for old description"'; exit 2; }
    NEW_OUT=$(run_one "$NEWF") || { verdict UNVERIFIED '"run_eval failed for new description"'; exit 2; }
    # Join results to eval-set by query; recall = correct on should_trigger=true, false-trigger on =false.
    OLD_OUT="$OLD_OUT" NEW_OUT="$NEW_OUT" SHADOW_JSON="$SHADOW_JSON" python3 - "$EVALSET" <<'PY'
import json, os, sys
evs = {q["query"]: bool(q["should_trigger"]) for q in json.load(open(sys.argv[1]))}
probe = json.loads(os.environ.get("SHADOW_JSON", "{}"))
def metrics(out):
    try: o = json.loads(out)
    except Exception: return None
    pos=neg=rec=fal=0
    for r in o.get("results", []):
        st = evs.get(r["query"]); trig = r.get("trigger_rate", 0) >= 0.5
        if st is True: pos += 1; rec += 1 if trig else 0
        elif st is False: neg += 1; fal += 1 if trig else 0
    return {"recall": rec/pos if pos else 1.0, "false_trigger": fal/neg if neg else 0.0, "pos": pos, "neg": neg}
old = metrics(os.environ.get("OLD_OUT","")); new = metrics(os.environ.get("NEW_OUT",""))
if old is None or new is None:
    print(json.dumps({"verdict":"UNVERIFIED","detail":{"reason":"run_eval output unparseable -> fail closed, human gate","probe":probe}})); sys.exit(2)
# Vacuous if there is NO should_trigger=true query (pos==0 => recall defaults to 1.0, measuring nothing on
# the axis a description change targets), OR if neither description activates any positive: measured nothing.
if old["pos"] == 0 or (old["recall"] == 0.0 and new["recall"] == 0.0):
    print(json.dumps({"verdict":"UNVERIFIED","detail":{"old":old,"new":new,"probe":probe,
          "reason":"recall axis measured nothing (pos=%d, recall %.2f->%.2f): a description change needs activating positive cases -> human gate" % (old["pos"],old["recall"],new["recall"])}})); sys.exit(2)
ok = (new["recall"] >= old["recall"]) and (new["false_trigger"] <= old["false_trigger"])
print(json.dumps({"verdict":"PASS" if ok else "REVERT","detail":{"old":old,"new":new,"probe":probe,
      "reason":"recall %.2f->%.2f, false-trigger %.2f->%.2f" % (old["recall"],new["recall"],old["false_trigger"],new["false_trigger"])}}))
sys.exit(0 if ok else 1)
PY
    exit $?
    ;;

  hook)
    HOOK="${1:?hook cmd template}"; MATRIX="${2:?fire-matrix.json}"
    [ -f "$MATRIX" ] || { verdict UNVERIFIED '"missing fire-matrix"'; exit 2; }
    blocks() { # input(stdin) -> 0 if the hook BLOCKS (non-zero exit or deny/block in output)
      local out rc
      out=$(printf '%s' "$1" | eval "$HOOK" 2>&1); rc=$?
      [ $rc -ne 0 ] && return 0
      printf '%s' "$out" | grep -qiE '"(deny|block)"|permissionDecision.*deny|⛔|BLOCKED' && return 0
      return 1
    }
    fails=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(len(d.get("deny",[])),len(d.get("allow",[])))' "$MATRIX")
    bad=0; report=""
    while IFS= read -r inp; do blocks "$inp" || { bad=$((bad+1)); report="$report deny-not-blocked"; }; done \
      < <(python3 -c 'import json,sys;[print(x["input"]) for x in json.load(open(sys.argv[1])).get("deny",[])]' "$MATRIX")
    while IFS= read -r inp; do blocks "$inp" && { bad=$((bad+1)); report="$report false-block"; }; done \
      < <(python3 -c 'import json,sys;[print(x["input"]) for x in json.load(open(sys.argv[1])).get("allow",[])]' "$MATRIX")
    [ "$bad" -eq 0 ] && { verdict PASS "\"matrix($fails) ok\""; exit 0; } || { verdict REVERT "\"$report\""; exit 1; }
    ;;

  script)
    SCMD="${1:?script cmd}"; GOLDEN="${2:?golden.json}"
    [ -f "$GOLDEN" ] || { verdict UNVERIFIED '"missing golden"'; exit 2; }
    bad=0
    while IFS=$'\t' read -r args want_exit want_sub; do
      out=$(eval "$SCMD $args" 2>&1); rc=$?
      [ -n "$want_exit" ] && [ "$rc" != "$want_exit" ] && bad=$((bad+1))
      [ -n "$want_sub" ] && ! printf '%s' "$out" | grep -qF "$want_sub" && bad=$((bad+1))
    done < <(python3 -c '
import json,sys
for c in json.load(open(sys.argv[1])):
    print("%s\t%s\t%s" % (c.get("args",""), c.get("expect_exit",""), c.get("expect_stdout_contains","")))' "$GOLDEN")
    [ "$bad" -eq 0 ] && { verdict PASS null; exit 0; } || { verdict REVERT "\"$bad golden mismatch(es)\""; exit 1; }
    ;;

  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
