#!/usr/bin/env python3
# PreToolUse hook (matcher: Bash).
#
# Denies a raw dump of a large Nimony `.nif` artifact via a shell pager/cat.
# If a Bash command is `cat`/`head`/`tail`/`less`/`more`/`bat` targeting a
# `.nif` path that exists and is > 15000 bytes, deny and steer the agent to the
# structural MCP tools (`nif_outline`/`nif_query`/`nif_render`) and the `/nif`
# command. This is the Bash-side companion of guard-nif-read.py, which guards
# the `Read` tool.
#
# Contract (docs.claude.com/en/docs/claude-code/hooks):
#   stdin  : JSON with `tool_name` and `tool_input` (Bash -> {"command": ...})
#   stdout : on deny, a PreToolUse decision object:
#              {"hookSpecificOutput": {"hookEventName": "PreToolUse",
#                                      "permissionDecision": "deny",
#                                      "permissionDecisionReason": "..."}}
#   allow  : exit 0 with no output.
# No-op (exit 0, no output) for any unrelated command. Never crash the tool:
# any error -> allow (exit 0).
#
# python3.7-safe, stdlib only.

import json
import os
import shlex
import sys

SIZE_LIMIT = 15000  # bytes

# Shell commands that dump a whole file to the terminal.
DUMP_CMDS = ("cat", "head", "tail", "less", "more", "bat")


def _candidate_paths(command):
    """Extract .nif path arguments from dump commands in a shell string.

    Splits on `;`, `&&`, `||`, `|` so a pipeline like `cat x.nif | grep foo` is
    handled. For each simple command whose executable is a known dump command,
    return its non-flag arguments that end in `.nif`.
    """
    paths = []
    # Normalise the common connectives to a single delimiter, then split.
    normalized = command
    for sep in ("&&", "||", ";", "|", "\n"):
        normalized = normalized.replace(sep, "\x00")
    for segment in normalized.split("\x00"):
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            # Unbalanced quotes etc. -> skip this segment safely.
            continue
        if not tokens:
            continue
        exe = os.path.basename(tokens[0])
        if exe not in DUMP_CMDS:
            continue
        for tok in tokens[1:]:
            if tok.startswith("-"):
                continue
            if tok.endswith(".nif"):
                paths.append(tok)
    return paths


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    if not raw:
        return 0

    try:
        data = json.loads(raw)
    except Exception:
        return 0

    if not isinstance(data, dict):
        return 0

    if data.get("tool_name") != "Bash":
        return 0

    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        return 0

    try:
        candidates = _candidate_paths(command)
    except Exception:
        return 0

    if not candidates:
        return 0  # not a .nif dump command -> no-op

    # Deny on the first big, existing .nif target.
    for path in candidates:
        try:
            if not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
        except Exception:
            continue
        if size <= SIZE_LIMIT:
            continue

        reason = (
            "Refused: this command dumps '{path}', a Nimony NIF artifact of "
            "{size} bytes (> {limit}). Piping a raw NIF S-expression stream "
            "through cat/head/tail/less/more/bat wastes tokens.\n"
            "Use the structural tools instead:\n"
            "  - MCP `nimlang.nif_outline(nif_file)` for top-level tags/symbols\n"
            "  - MCP `nimlang.nif_query(nif_file, needle)` to fetch just the "
            "matching subtrees\n"
            "  - MCP `nimlang.nif_render(nif_file, needle)` for compact "
            "pseudo-Nim\n"
            "  - the `/nif <file.nif> [needle]` command as a shortcut\n"
            "If you truly need raw bytes (rare), slice a bounded range with "
            "`sed -n '1,40p'` rather than dumping the whole file."
        ).format(path=path, size=size, limit=SIZE_LIMIT)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        sys.stdout.write(json.dumps(output))
        return 0

    return 0  # no big .nif target -> allow


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Absolutely never break the Bash tool.
        sys.exit(0)
