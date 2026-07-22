---
description: Run a Nimony program under the aowli interpreter and report its call-tree trace.
argument-hint: "[file]"
---

Trace the execution of `$ARGUMENTS` (a Nimony `.nim` file) under the aowli
tree-walking interpreter and report the call tree.

Steps:

1. Determine the target file from `$ARGUMENTS`. If no file is given, infer the
   `.nim` file currently in focus. This tool is Nimony-only: it compiles the
   program to typed NIF and interprets it with `~/aowli/bin/aowli-interp`.

2. Call the MCP tool **`nimlang.trace`** with `{file}` (optionally
   `{file, max_lines}` to cap the call tree). Do NOT compile or run
   `aowli-interp` by hand. The tool compiles the file to a temp nimcache,
   locates the main module's `.s.nif`, runs `aowli-interp --trace`, and returns
   `{ok, trace, stdout, exit_code}`.

3. Report:
   - `ok` / failed (from `exit_code`),
   - the `trace`: the depth-indented call tree — `→ callee(args) :LINE` on
     enter, `← <ret>` on exit, ending in a `-- trace: N calls, max depth M`
     summary. Present it as a fenced block.
   - the program's `stdout` if non-empty.

4. If the tool returns `{error: ...}` (e.g. a compile failure), report that
   message and, for compile errors, hand off to `/check` or `/explain-failure`.
