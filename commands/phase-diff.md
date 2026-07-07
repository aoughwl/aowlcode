---
description: Compile a file with Nimony and structurally diff its nimcache phase artifacts.
argument-hint: "<file.nim> [phaseA phaseB]"
---

Compile `$ARGUMENTS` with Nimony and diff the NIF artifacts it produces across
compilation phases, so you can see exactly which lowering pass changed the IR.
This is a Nimony-only workflow (Nim has no NIF artifacts).

Steps:

1. Take the `.nim` file from `$ARGUMENTS`. Optionally the user names two phase
   suffixes to compare (default: the parsed `.p.nif` vs the semchecked
   `.s.nif`).

2. Ensure artifacts exist: call **`nimlang.compile`** with
   `{file, toolchain: "nimony"}` (equivalently `bin/nimony c FILE` from the
   Nimony repo). This writes `nimcache/*.nif`.

3. Locate the artifacts in `nimcache/` for this module. The phase pipeline and
   suffixes are:
   - `.p.nif` — parsed NIF (nifler front-end)
   - `.s.nif` — semchecked / front-end lowered (nimony); `.s.idx.nif` is its index
   - `.x.nif` / `.dce.nif` — hexer lowering + dead-code elimination
   - then Leng/C generation (lengc)
   `.deps.nif` files are dependency lists, not phase bodies.

4. Call **`nimlang.nif_diff`** with `{file_a, file_b}` for the chosen adjacent
   phases. It returns a compact `{changed:[...]}` (unified diff, context 1,
   headers trimmed, unchanged regions collapsed). Never diff by reading both
   files raw.

5. Report which phase introduced the change and what the structural delta means
   (map tags via the `nif-format` skill / `~/nimony/doc/tags.md`). Per
   `~/nimony/AGENTS.md`, assume `nifler`/`nifmake`/`lengc` are stable — suspect
   `nimony` (sem, `.s`) or `hexer` (lowering, `.x`/`.dce`). For deep hunts,
   delegate to the `nif-inspector` subagent.
