---
description: Run the Nimony AGENTS.md debug loop and report only structured findings.
argument-hint: "[file.nim]"
---

Drive the Nimony compiler debug workflow from `~/nimony/AGENTS.md` for the bug
in `$ARGUMENTS` (a minimal reproducing `.nim` file). This is for debugging the
**Nimony toolchain itself**, not user Nim code — for plain compile errors use
`/check`.

Working assumption (from AGENTS.md): `nifler`, `nifmake`, and `lengc` are
stable. Most bugs live in **Nimony** (sem/front-end) or **Hexer** (lowering).

Steps (run from the `~/nimony` repo):

1. Build the toolchain if needed: `nim c -r src/hastur build nimony`
   (or `build all` for the full set). Report build failures via
   `nimlang.compile` parsing / the trimmed diagnostics.

2. Reproduce with the smallest input. Produce artifacts with:
   - `bin/nimony c <file.nim>`, or
   - `nim c -r src/hastur debug <file.nim>` (convenience wrapper), or
   - `hastur bug` / `hastur rep` for fast turnaround.

3. Inspect `nimcache/` NIF artifacts with the MCP tools ONLY — never raw-read
   `.nif`:
   - `nimlang.nif_outline` for structure,
   - `nimlang.nif_query` to fetch the suspect subtree,
   - `nimlang.nif_diff` (or `/phase-diff`) across `.p -> .s -> .x/.dce` to find
     the phase that mis-lowered.
   Delegate heavy reading to the `nif-inspector` subagent.

4. Validate with `hastur test <file-or-dir>` (many minimal cases live in
   `tests/nimony/`). If a fix changes recorded NIF, refresh expected results with
   `hastur --overwrite test ...` — those diffs are part of code review.

5. Report ONLY: the failing phase, the offending tag/symbol, the likely
   `src/nimony/` or `src/hexer/` location, and the structured diagnostics — not
   raw NIF dumps or build noise.
