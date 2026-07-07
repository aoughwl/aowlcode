---
description: Build a linked Nim or Nimony executable and report structured diagnostics plus the binary path.
argument-hint: "[file] [run] [release] [toolchain: nim|nimony|auto]"
---

Build `$ARGUMENTS` (a `.nim` file, optionally followed by `run`, `release`,
and/or an explicit toolchain) into an actual executable, and report the result
concisely.

Use this instead of `/check` when you need a runnable binary, not just a
type-check. `/check` (and the `compile` tool) only *type-check* Nim — they never
produce a linked executable; `build` does.

Steps:

1. Determine the target file and toolchain from `$ARGUMENTS` (toolchain defaults
   to `auto`; honor an explicit `nim`/`nimony` and `NIMLANG_TOOLCHAIN`). Treat
   the word `run` as request-to-run and `release` as `-d:release`.

2. Call the MCP tool **`nimlang.build`** with `{file, toolchain, run, release}`.
   Do NOT run `nim c` / `nimony c` by hand unless the MCP server is unavailable.
   It returns `{ok, toolchain, diagnostics, binary?, run?}` — noise already
   stripped, `ok` computed by parsing for `Error:` (not the unreliable exit
   code).

3. Report:
   - `ok` / failed, and each diagnostic as `file(line,col) Severity: message`,
     errors first;
   - on success, the **binary** path (Nim: next to the source; Nimony:
     `nimcache/<hash>/<module>`);
   - if `run` was requested, the program's captured `run.output` and
     `run.exit_code`, kept separate from the diagnostics.

Works for BOTH toolchains: Nim (`nim c`) and Nimony (`nimony c`).
