#!/usr/bin/env python3
# PreCompact hook (no matcher — PreCompact is not tool-scoped).
#
# Fires right before context gets compacted/discarded. A hook script can't
# author memory itself, so its only job here is to remind the agent to run
# `/land` FIRST if there are durable, cross-session learnings from this
# session that haven't been flushed to
# /home/savant/.claude/projects/-home-savant/memory/ yet — because after
# compaction, anything not written down is gone.
#
# Contract (docs.claude.com/en/docs/claude-code/hooks):
#   stdin  : JSON with at least `hook_event_name` (== "PreCompact"); other
#            fields vary by harness version and are not required here.
#   stdout : optionally
#              {"hookSpecificOutput": {"hookEventName": "PreCompact",
#                                      "additionalContext": "..."}}
#   Always exits 0. Never blocks or fails the compact: any error -> exit 0
#   doing nothing.
#
# python3.7-safe, stdlib only.

import json
import sys

NUDGE = (
    "Reminder: this context is about to be compacted. If this session "
    "produced durable, cross-session learnings (non-obvious gotchas, "
    "toolchain quirks, an aowl-stack M-log entry) that haven't been flushed "
    "to memory yet, run `/land` first to write them to "
    "/home/savant/.claude/projects/-home-savant/memory/ and commit+push the "
    "working repo before they're discarded."
)


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0

    # Best-effort: parse stdin if present, but don't require any particular
    # shape. This hook nudges unconditionally on every PreCompact — it has no
    # way to know from here whether learnings were already flushed.
    if raw:
        try:
            json.loads(raw)
        except Exception:
            pass  # still fine to nudge even if stdin wasn't valid JSON

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": NUDGE,
        }
    }
    try:
        sys.stdout.write(json.dumps(output))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Absolutely never break compaction.
        sys.exit(0)
