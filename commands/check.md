---
description: Compile-check a Nim or Nimony file and report only structured diagnostics.
argument-hint: "[file] [toolchain: nim|nimony|auto]"
---

Compile-check `$ARGUMENTS` (a `.nim` file, optionally followed by an explicit
toolchain) and report the result concisely.

Steps:

1. Determine the target file and toolchain from `$ARGUMENTS`. If no file is
   given, ask or infer the file currently in focus. Toolchain defaults to
   `auto` (walk up from the file: a `nimony.paths` / `nimony.cfg` or a
   `nim.cfg` mentioning nimony => Nimony; otherwise Nim). Honor an explicit
   `nim` or `nimony` argument, and the `NIMLANG_TOOLCHAIN` env var.

2. Call the MCP tool **`nimlang.compile`** with `{file, toolchain}`. Do NOT run
   `nim`/`nimony` by hand unless the MCP server is unavailable. The tool returns
   `{ok, toolchain, stage, diagnostics:[{file,line,col,severity,message}]}`.

3. Report:
   - the resolved toolchain (Nim via `nim check`, or Nimony via `nimony c`),
   - `ok` / failed. IMPORTANT: `nimony c` can exit 0 even on failure, so trust
     the tool's `ok` field (it treats any `Error:` diagnostic as failure), not
     the process exit code.
   - each diagnostic as `file(line,col) Severity: message`, errors first.

4. If it failed, give a one-line diagnosis and, when useful, point at the
   relevant source. For Nimony compiler-internal failures (not user code), hand
   off to `/nimony-bug` or the `debug-loop` skill.

Works for BOTH toolchains: Nim (`nim check --hints:off --colors:off`) and
Nimony (`nimony c`, build-driver noise stripped by the plugin's hook).
