---
name: nif-format
description: >-
  Read this when working with NIF (.nif) artifacts or the Nimony compiler phase
  pipeline: the S-expression IR format, its tag vocabulary, the phase suffixes
  (.p/.s/.x/.dce), and which tool produces which artifact. Use before reading or
  diffing nimcache/*.nif files.
---

# NIF format & the Nimony phase pipeline

NIF is the S-expression IR that the Nimony toolchain passes between phases. Files
live in `nimcache/*.nif`. They are large — inspect them with the plugin's MCP
tools (`nimlang.nif_outline`, `nimlang.nif_query`, `nimlang.nif_diff`) or the
`/nif` and `/phase-diff` commands. Never raw-read a big `.nif` (the Read hook
blocks files > 15000 bytes).

## Pipeline (tool -> artifact)

    nifler  : Nim source  -> parsed NIF          (.p.nif)
    nimony  : sem-check + front-end lowering      (.s.nif, index .s.idx.nif)
    hexer   : lowering passes + dead-code elim     (.x.nif, .dce.nif)
    lengc   : C/C++ backend from Leng NIF          (C output)

Supporting: `nifmake` (build driver, emits `nifmake:`/`FAILURE:` noise),
`niflink` (linker), `nimsem` (idetools/semantic queries), `hastur` (build/test).

Suffix cheat sheet:
- `.p.nif`   — parsed (nifler). Untyped, close to source syntax.
- `.s.nif`   — semchecked (nimony). Typed forms appear (types in tag slots).
- `.s.idx.nif` — symbol index for the `.s` module.
- `.x.nif`   — hexer-lowered.
- `.dce.nif` — after dead-code elimination.
- `.deps.nif` — dependency list, NOT a phase body. Skip when diffing IR.

When a bug appears, `~/nimony/AGENTS.md` says assume `nifler`/`nifmake`/`lengc`
are stable; suspect `nimony` (`.s`) or `hexer` (`.x`/`.dce`). `/phase-diff`
across adjacent phases pinpoints the mis-lowering pass.

## Tag vocabulary (condensed)

Nodes are `(tag child ...)`. Common families:

- Declarations: `(proc D ...)`, `(func D ...)`, `(iterator ...)`, `(template ...)`,
  `(macro ...)`, `(converter ...)`, `(method ...)`, `(type D ...)`,
  `(var/let/const/gvar/glet/cursor D E P T .X)` (D=name, E=export, P=pragmas,
  T=type, X=value/init), `(param ...)`, `(fld ...)`/`(efld ...)` fields,
  `(typevar ...)`, `(module)`.
- Types: `(object .T (fld ...)*)`, `(enum (efld ...)*)`, `(proctype ...)`,
  `(params (param ...)*)`, `(ptr T)`, `(ref T)`, builtins `(i N)` `(u N)` `(f N)`
  `(c N)` `(bool)` `(void)`; nil annotations `(notnil)`/`(nil)`/`(unchecked)`.
- Statements: `(stmts S*)`, `(asgn X X)`, `(if (elif X X)+ (else X)?)`, `(when ...)`,
  `(case X (of (ranges ...) S)+ ...)`, `(while X S)`, `(for ...)`, `(ret .X)`,
  `(yld .X)`, `(break)`, `(continue)`, `(block .D X)`, `(scope S*)`.
- Expressions: `(call X X*)`, `(cmd X X*)`, `(dot X Y ...)` field access,
  `(at ...)` index / generic instantiation, `(deref X)`, `(addr X)`, `(conv T X)`,
  `(cast T X)`, arithmetic/compare `(add/sub/mul/div/eq/lt ... T X X)`,
  constructors `(oconstr T (kv Y X)*)`, `(aconstr T X*)`, literals `(suf LIT STR)`,
  `(true)`/`(false)`/`(nil ...)`.
- Leng-only lowering: `(lab D)`, `(jmp Y)`, `(store X X)`, type qualifiers
  `(atomic)`/`(ro)`/`(restrict)`/`(cppref)`.
- `(err ...)` marks an error node — a red flag when hunting bugs.

The enum column in the source table (NimonyExpr, LengExpr, NiflerKind, ...) tells
you which phase/dialect a tag is legal in.

## The long tail

This is a summary only. The full, authoritative tag table (~375 rows, including
`unpackflat`/`unpacktup`/`unpackdecl` and every slot's meaning) is at
**`~/nimony/doc/tags.md`** — link to it and grep it; do not inline it.
