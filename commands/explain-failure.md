---
description: Explain a Nim or Nimony compile failure in one shot — report only the verdict and culprit.
argument-hint: "[file] [toolchain: nim|nimony|auto]"
---

Diagnose why `$ARGUMENTS` fails to compile and report ONLY the verdict and the
culprit. This is the one-call recipe that replaces compile → list → outline →
query.

Steps:

1. Determine the target file and toolchain from `$ARGUMENTS`. If no file is
   given, infer the file in focus. Toolchain defaults to `auto` (walk up from
   the file: a `nimony.paths` / `nimony.cfg` or a `nim.cfg` mentioning nimony
   => Nimony; otherwise Nim). Honor an explicit `nim`/`nimony` argument and the
   `NIMLANG_TOOLCHAIN` env var.

2. Call the MCP tool **`nimlang.explain_failure`** with `{file, toolchain}`. Do
   NOT run `nim`/`nimony` by hand, and do NOT chain `compile`/`outline`/
   `nif_query` yourself — this tool does the whole thing. It returns
   `{ok, toolchain, verdict, diagnostics, culprit?}`.

3. Report tersely:
   - the resolved toolchain and `ok`/failed (trust the tool's `ok`, not the
     process exit code — `nimony c` can exit 0 on failure),
   - the ≤5-line `verdict`,
   - the `culprit`. For Nim this is ±3 source lines around the first error; for
     Nimony it is the smallest NIF node spanning the error position, already
     extracted for you.

   Do NOT dump the full diagnostics list or any NIF file — the verdict and
   culprit are the answer.

Works for BOTH toolchains: Nim (`nim check`, source-line culprit) and Nimony
(`nimony c`, NIF-node culprit from the failing phase artifact). For Nimony
compiler-internal failures, hand off to `/nimony-bug` or the `debug-loop` skill.
