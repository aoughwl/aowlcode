---
description: Delta-debug a failing Nim or Nimony file down to a minimal still-failing repro.
argument-hint: "[file] [toolchain: nim|nimony|auto]"
---

Reduce `$ARGUMENTS` to the smallest source that still reproduces its compile
failure, and report the minimal repro plus how much smaller it got.

Steps:

1. Determine the target file and toolchain from `$ARGUMENTS`. If no file is
   given, infer the file in focus. Toolchain defaults to `auto` (walk up from
   the file: a `nimony.paths` / `nimony.cfg` or a `nim.cfg` mentioning nimony
   => Nimony; otherwise Nim). Honor an explicit `nim`/`nimony` argument and the
   `NIMLANG_TOOLCHAIN` env var.

2. Call the MCP tool **`nimlang.shrink`** with `{file, toolchain}`. It iteratively
   drops top-level statements/lines while preserving the FIRST `Error:` message,
   and returns `{original_lines, minimal_lines, minimal_source, kept_error}`. Do
   NOT try to minimize the file by hand.

3. Report:
   - the line-count reduction: `original_lines` → `minimal_lines` (e.g.
     "142 → 9 lines"),
   - the `kept_error` — the failure the repro still triggers,
   - the `minimal_source` as a fenced code block.

Works for BOTH toolchains: Nim (`nim check`) and Nimony (`nimony c`, trusting the
`ok`/`Error:` signal, not the exit code). The reduction is bounded in
iterations/time, so the result is minimal-ish, not provably minimal — good enough
for a bug report or a focused fix.
