#!/bin/bash
# PostToolUse hook: warn when any skills/<name>/SKILL.md is edited mid-session.
#
# Why: the main agent's in-memory copy of SKILL.md is loaded at session start.
# Editing SKILL.md mid-session does NOT refresh the main agent's mental model.
# Subagents dispatched afterwards can re-read the file fresh from disk, but
# any validation depending on the main agent's reasoning will still reference
# the pre-edit version. The clean fix is `claude --resume <session_id>`.
#
# Triggered for Edit/Write/MultiEdit. Reads the tool input JSON from stdin and
# emits a system-reminder back via hookSpecificOutput.additionalContext.

set -euo pipefail

# Bounded stdin read via bash builtin (timeout(1) isn't on stock macOS).
# Fail open — this hook is advisory only and never blocks tool calls.
input=""
if ! IFS= read -rd '' -t 5 input; then
  rc=$?
  if [ "$rc" -gt 128 ]; then
    exit 0  # timeout
  fi
fi
if [ -z "$input" ]; then
  exit 0
fi
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
session_id=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || echo "")

if [[ -z "$file_path" ]]; then
  exit 0
fi

# Match absolute or relative paths ending in skills/<name>/SKILL.md.
if [[ "$file_path" =~ (^|/)skills/[^/]+/SKILL\.md$ ]]; then
  skill_name=$(printf '%s' "$file_path" | sed -E 's|.*/skills/([^/]+)/SKILL.md$|\1|')

  if [[ -n "$session_id" ]]; then
    resume_cmd="claude --resume $session_id"
  else
    resume_cmd="claude --resume <session_id>"
  fi

  msg="WARNING: skills/${skill_name}/SKILL.md was modified mid-session. The main agent's in-memory skill content is from session start and is NOT refreshed by this edit. Subagents dispatched after this point can re-read the file fresh from disk if instructed, but the main agent's own reasoning still references the pre-edit version. Before running validation that depends on the new rules, tell the user verbatim: \"Please restart this session to reload the updated ${skill_name} skill from disk: ${resume_cmd}\""

  jq -n --arg msg "$msg" '{
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: $msg
    }
  }'
fi

exit 0
