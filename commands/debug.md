---
description: Run a Nimony program under the aowli batch breakpoint engine and report the captured frame locals.
argument-hint: "[file] [line ...]"
---

Debug `$ARGUMENTS` (a Nimony `.nim` file plus one or more breakpoint lines)
under the aowli batch breakpoint / tracepoint engine and report the captured
variable values.

This is NON-interactive: it runs the program to completion, and each time a
breakpoint's line (or routine) is reached it snapshots the current frame's
locals. No pause/resume/stepping — it records every hit and continues. Use it to
see what a variable actually holds at a line, without editing the program to add
`echo`/`write` statements.

Steps:

1. Determine the target `.nim` file and the breakpoints from `$ARGUMENTS`.
   Bare integers are line numbers (`breaks`); a `func:NAME` token is a
   routine-entry breakpoint (`break_funcs`). If no file is given, infer the
   `.nim` file currently in focus. Nimony-only.

2. Call the MCP tool **`nimlang.debug`** with `{file, breaks, break_funcs}`
   (at least one of `breaks`/`break_funcs` is required). Do NOT compile or run
   `aowli-dbg` by hand. The tool compiles the file to a temp nimcache, locates
   the main module's `.s.nif`, runs `~/aowli/bin/aowli-dbg` with the
   `--break:LINE` / `--break-func:NAME` flags, and returns
   `{ok, captures, stdout, exit_code}`.

3. Report:
   - `ok` / failed (from `exit_code`),
   - the `captures`: one block per hit — `break @ line N in routine()` followed
     by `  name = value` for each local at that point. Present it as a fenced
     block.
   - the program's `stdout` if non-empty.

4. If the tool returns `{error: ...}` (e.g. a compile failure), report that
   message and, for compile errors, hand off to `/check` or `/explain-failure`.

Note: captures are taken at statement ENTRY, so a variable shows its value
*before* the statement on that line runs. To see a value after an assignment,
break on the following line.
