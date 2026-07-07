#!/usr/bin/env python3
# PreToolUse hook (matcher: Read).
#
# Denies a raw `Read` of a Nimony `.nif` artifact when the file is large
# (> 15000 bytes). Raw NIF S-expression streams are enormous and burn tokens;
# the plugin ships MCP tools that read them structurally instead. This hook
# steers the agent to those tools.
#
# v0.2 "transform-not-block": on deny we ALSO compute a compact top-level
# outline of the NIF file (a tiny self-contained paren-matcher, no imports
# from mcp/server.py) and embed it in `permissionDecisionReason`, so the model
# gets the useful compact version in the SAME turn instead of a bare refusal.
# Any failure in the outline step falls back to the plain deny message.
#
# Contract (docs.claude.com/en/docs/claude-code/hooks):
#   stdin  : JSON with `tool_name` and `tool_input` (Read -> {"file_path": ...})
#   stdout : on deny, a PreToolUse decision object:
#              {"hookSpecificOutput": {"hookEventName": "PreToolUse",
#                                      "permissionDecision": "deny",
#                                      "permissionDecisionReason": "..."}}
#   allow  : exit 0 with no output.
# Never crash the tool: any error -> allow (exit 0).
#
# python3.7-safe, stdlib only.

import json
import os
import sys

SIZE_LIMIT = 15000  # bytes
OUTLINE_FORM_CAP = 60  # max top-level forms embedded in the deny reason
OUTLINE_READ_CAP = 400000  # bytes of NIF text to scan (bound work)


def _nif_parse_forms(text):
    """Minimal self-contained paren-matching scanner over a NIF stream.

    Returns a flat list of forms, each: {start, end, depth, line, tokens}.
    tokens = the atom/string tokens that are DIRECT children of the form
    (nested lists are their own forms). Handles NIF string literals so parens
    inside strings do not confuse the scanner. Dependency-free (does NOT import
    from mcp/server.py) so the hook stays standalone.
    """
    forms = []
    stack = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if c == '(':
            form = {'start': i, 'end': n, 'depth': len(stack),
                    'line': line, 'tokens': []}
            stack.append(form)
            forms.append(form)
            i += 1
            continue
        if c == ')':
            if stack:
                stack.pop()['end'] = i + 1
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == '"':
                    break
                if text[j] == '\n':
                    line += 1
                j += 1
            tok = text[i:j + 1]
            i = j + 1
        else:
            j = i
            while j < n and (not text[j].isspace()) and text[j] not in '()':
                j += 1
            tok = text[i:j]
            i = j
        if stack:
            stack[-1]['tokens'].append(tok)
    return forms


def _base_tag(tok):
    """Strip NIF line-info suffix (starting at '@') from a token."""
    if not tok:
        return ''
    return tok.split('@', 1)[0]


def _clean_name(tok):
    if not tok:
        return ''
    name = tok.split('@', 1)[0]
    return name.lstrip(':')


def _nif_outline(file_path):
    """Compact top-level outline: list of "tag name" for the direct children
    of the top `stmts` container. Bounded to OUTLINE_FORM_CAP forms. Returns a
    list of strings, or [] if nothing useful could be extracted.
    """
    with open(file_path, 'r', errors='replace') as fh:
        text = fh.read(OUTLINE_READ_CAP)

    forms = _nif_parse_forms(text)

    stmts = None
    for f in forms:
        if f['tokens'] and _base_tag(f['tokens'][0]) == 'stmts':
            stmts = f
            break

    picked = []
    if stmts is not None:
        child_depth = stmts['depth'] + 1
        lo, hi = stmts['start'], stmts['end']
        for f in forms:
            if f['depth'] != child_depth:
                continue
            if f['start'] < lo or f['end'] > hi:
                continue
            picked.append(f)
    else:
        for f in forms:
            if f['depth'] == 0 and f['tokens']:
                picked.append(f)

    out = []
    for f in picked:
        toks = f['tokens']
        if not toks:
            continue
        tag = _base_tag(toks[0])
        name = _clean_name(toks[1]) if len(toks) > 1 else ''
        if name:
            out.append("(%s %s)  @L%d" % (tag, name, f['line']))
        else:
            out.append("(%s)  @L%d" % (tag, f['line']))
        if len(out) >= OUTLINE_FORM_CAP:
            break
    return out


def _outline_block(file_path):
    """Best-effort compact outline block for the deny reason. Never raises."""
    try:
        outline = _nif_outline(file_path)
    except Exception:
        return ""
    if not outline:
        return ""
    header = (
        "\nCompact top-level outline (first {n} form(s), computed in-hook "
        "so you don't have to re-fetch):\n"
    ).format(n=len(outline))
    return header + "\n".join("  " + row for row in outline)


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

    if data.get("tool_name") != "Read":
        return 0

    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return 0

    if not file_path.endswith(".nif"):
        return 0

    try:
        size = os.path.getsize(file_path)
    except Exception:
        # Can't stat it -> let Read handle the error normally.
        return 0

    if size <= SIZE_LIMIT:
        return 0

    reason = (
        "Refused: '{path}' is a Nimony NIF artifact of {size} bytes "
        "(> {limit}). Reading raw NIF S-expression streams wastes tokens.\n"
        "Use the structural tools instead:\n"
        "  - MCP `nimlang.nif_outline(nif_file)` for top-level tags/symbols\n"
        "  - MCP `nimlang.nif_query(nif_file, needle)` to fetch just the "
        "matching subtrees\n"
        "  - MCP `nimlang.nif_diff(a, b)` to compare phase artifacts\n"
        "  - the `/nif <file.nif> [needle]` command as a shortcut\n"
        "If you truly need the raw bytes (rare), read a bounded slice with "
        "`sed -n` / Bash rather than the whole file."
    ).format(path=file_path, size=size, limit=SIZE_LIMIT)

    # transform-not-block: embed a compact outline so the model gets the useful
    # version this same turn. Best-effort; never let it break the deny.
    try:
        block = _outline_block(file_path)
        if block:
            reason = reason + "\n" + block
    except Exception:
        pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(output))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Absolutely never break the Read tool.
        sys.exit(0)
