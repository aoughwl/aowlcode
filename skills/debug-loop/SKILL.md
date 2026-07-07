---
name: debug-loop
description: >-
  Read this when debugging the Nimony compiler/toolchain itself (miscompiles,
  bad NIF, phase regressions) rather than plain user Nim errors. Encodes the
  ~/nimony/AGENTS.md workflow: build -> reproduce -> nimcache diff -> test/rep ->
  --overwrite, and where to look.
---

# Nimony compiler debug loop

From `~/nimony/AGENTS.md`. Use for bugs in the compiler pipeline
(nifler -> nimony -> hexer -> lengc), not for ordinary user compile errors
(use `/check` for those). Trigger the `/nimony-bug` command to run this.

## Working assumption

Assume **`nifler`, `nifmake`, and `lengc` are stable**. Most bugs are in
**`nimony`** (semantic analysis / front-end lowering, `.s.nif`) or **`hexer`**
(lowering passes + Leng generation, `.x.nif` / `.dce.nif`).

## Loop (run from `~/nimony`)

1. **Build the toolchain**
   `nim c -r src/hastur build nimony`   (or `build all`).
2. **Reproduce small.** Shrink to the smallest failing `.nim`. Minimal cases
   already live in `tests/nimony/` — start there.
3. **Produce artifacts**
   `bin/nimony c mybug.nim`  — or the convenience wrapper
   `nim c -r src/hastur debug mybug.nim`. Use `hastur bug` / `hastur rep` for
   fast turnaround.
4. **Inspect `nimcache/` diffs.** Compare phase artifacts to find where the IR
   goes wrong — use `nimlang.nif_diff` / `/phase-diff` across
   `.p -> .s -> .x/.dce`, and `nimlang.nif_query` to pull the suspect subtree.
   `(err ...)` nodes are red flags. NEVER raw-read big `.nif` files; delegate
   heavy reading to the `nif-inspector` subagent. (See the `nif-format` skill.)
5. **Localize in source.** Front-end/sem issue => `src/nimony/`. Lowering/Leng
   issue => `src/hexer/`. `src/nifler/` and `src/lengc/` only when evidence
   points there. Test/build tooling => `src/hastur.nim`.
6. **Validate.** `hastur test <file>` or `hastur test <dir>` to confirm the fix
   and catch regressions.
7. **Refresh expected results.** Tests embed large produced NIF. When a
   legitimate change alters recorded output, run `hastur --overwrite` (all) or
   `hastur --overwrite test <case>` (one). The resulting diffs ARE part of code
   review — inspect them, don't rubber-stamp.

## Report

Return only structured findings: failing phase, offending tag/symbol, likely
`src/nimony/` or `src/hexer/` location, and the parsed diagnostics — not raw NIF
dumps or `nifmake:`/`FAILURE:` build noise (the plugin's Bash hook already trims
that from tool output).
