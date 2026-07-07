#!/usr/bin/env python3
# PostToolUse hook (matcher: Bash).
#
# When a Bash command invoked a Nim/Nimony build tool
# (`nimony`, `hastur`, `nim c`/`nim check`, `nimble`), its output is full of
# build-driver noise: `nifmake:` progress lines, `FAILURE:` banners, and
# `niflink` linker chatter. This hook strips that noise and surfaces just the
# compiler diagnostics back to the model as `additionalContext`.
#
# Contract (docs.claude.com/en/docs/claude-code/hooks):
#   stdin  : JSON with `tool_name`, `tool_input` (Bash -> {"command": ...})
#            and `tool_response` (the tool result; shape varies).
#   stdout : optionally
#              {"hookSpecificOutput": {"hookEventName": "PostToolUse",
#                                      "additionalContext": "..."}}
#   No-op for unrelated commands (exit 0, no output).
# Never crash the tool: any error -> exit 0 silently.
#
# python3.7-safe, stdlib only.

import json
import re
import sys

# Commands whose output we know how to trim.
BUILD_CMD_RE = re.compile(r"\b(nimony|hastur|nimble)\b|\bnim\s+(c|check|cpp|compile)\b")

# Noise lines to drop.
NOISE_PREFIXES = ("nifmake:", "FAILURE:", "niflink")

# Shared Nim/Nimony diagnostic line:  file(line, col) Error|Warning|Hint|Trace: msg
DIAG_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),\s*(?P<col>\d+)\)\s+"
    r"(?P<sev>Error|Warning|Hint|Trace):\s*(?P<msg>.*)$"
)


def is_noise(line):
    stripped = line.lstrip()
    for pre in NOISE_PREFIXES:
        if stripped.startswith(pre):
            return True
    return False


def extract_text(tool_response):
    # tool_response shape varies across versions; be liberal.
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        parts = []
        for key in ("stdout", "stderr", "output", "content", "text"):
            val = tool_response.get(key)
            if isinstance(val, str):
                parts.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
        return "\n".join(parts)
    if isinstance(tool_response, list):
        parts = []
        for item in tool_response:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


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
    command = ""
    if isinstance(tool_input, dict):
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            command = cmd

    if not command or not BUILD_CMD_RE.search(command):
        return 0  # not a build command -> no-op

    text = extract_text(data.get("tool_response"))
    if not text:
        return 0

    lines = text.splitlines()

    kept = []
    diagnostics = []
    dropped = 0
    for line in lines:
        if is_noise(line):
            dropped += 1
            continue
        kept.append(line)
        if DIAG_RE.match(line.strip()):
            diagnostics.append(line.strip())

    if dropped == 0:
        return 0  # nothing to trim -> stay a no-op

    # Build a compact summary. Prefer diagnostics; if none, show trimmed output.
    summary_parts = []
    has_error = any(
        DIAG_RE.match(d) and DIAG_RE.match(d).group("sev") == "Error"
        for d in diagnostics
    )
    if has_error:
        summary_parts.append(
            "Build FAILED (an `Error:` diagnostic was found; note nimony `c` "
            "may still exit 0 on failure)."
        )

    if diagnostics:
        summary_parts.append("Diagnostics (build noise stripped):")
        summary_parts.append("\n".join(diagnostics[:200]))
    else:
        cleaned = "\n".join(kept).strip()
        if not cleaned:
            return 0
        # Bound the payload so we don't reintroduce a token blowup.
        if len(cleaned) > 4000:
            cleaned = cleaned[:4000] + "\n... [trimmed]"
        summary_parts.append(
            "Trimmed {n} nifmake/FAILURE/niflink noise line(s). "
            "Cleaned output:".format(n=dropped)
        )
        summary_parts.append(cleaned)

    context = "\n".join(summary_parts)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }
    sys.stdout.write(json.dumps(output))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
