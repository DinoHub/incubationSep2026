#!/usr/bin/env bash
# Example bundled script. The agent RUNS this (its code never enters context —
# only this script's output does), so scripts are cheaper and more reliable than
# asking the agent to regenerate equivalent code each time.
#
# Two rules the docs insist on:
#   1. Solve, don't defer — handle the empty/error case HERE with an unambiguous
#      marker, instead of crashing and hoping the agent recovers.
#   2. No voodoo constants — justify every magic value in a comment.
set -euo pipefail

# 30s: typical operation completes well under this; the margin covers slow I/O.
TIMEOUT_SECONDS=30

# Replace with whatever the skill actually needs to gather.
if <condition-for-no-input>; then
  echo "__NO_INPUT__"   # SKILL.md checks for this and tells the user, then stops.
else
  timeout "${TIMEOUT_SECONDS}s" <command-that-produces-the-input>
fi
