---
name: nim-vs-nimony
description: >-
  Read this before writing, compiling, or debugging code that might be Nimony
  rather than Nim 2. Covers which toolchain/binary to use for what, how to detect
  which one a project targets, and the concrete feature-set differences.
  Key rule: do NOT assume Nim 2's feature set when the target is Nimony.
---

# Nim vs Nimony

Nimony is a from-scratch reimplementation of Nim (the future "Nim 3"), built
around NIF. It is a DIFFERENT compiler with a DIFFERENT, smaller feature set.
Do not assume Nim 2 semantics or stdlib when working in a Nimony project — read
what is actually available first.

## Which toolchain / binary

| Task                | Nim                                      | Nimony                                        |
|---------------------|------------------------------------------|-----------------------------------------------|
| compiler binary     | `nim`   (`~/Nim/bin`)                    | `nimony` (`~/nimony/bin`)                      |
| check for errors    | `nim check --hints:off --colors:off F`   | `nimony c F`  (strip `nifmake:` noise)         |
| compile & run       | `nim c -r F`                             | `bin/nimony c -r F`                            |
| def / uses / outline| `nimsuggest --stdin` (`def`/`use`/`outline`) | `nimsem idetools --track FILE,line,col`    |
| IR artifacts        | none                                     | `nimcache/*.nif` (see `nif-format` skill)      |
| build / test        | `nimble`, `nim c`                        | `hastur` (`build`/`test`/`bug`/`rep`), `nifmake` |

Prefer the plugin's MCP tools, which pick the right binary for you:
`nimlang.compile`, `nimlang.outline`, `nimlang.defs_uses` all take
`toolchain="auto"`.

### Detecting the toolchain (auto)

Walk UP from the target file:
- a `nimony.paths`, `nimony.cfg`, or a `nim.cfg` that mentions nimony => **Nimony**
- otherwise => **Nim**

Always allow an explicit override (`toolchain: "nim" | "nimony"`) and honor the
`NIMLANG_TOOLCHAIN` env var. `nimsuggest` is Nim-only; for Nimony, `outline`
falls back to a regex scan of the `.nim` source and def/uses uses `nimsem`.

IMPORTANT: `nimony c` may exit 0 even on failure. Treat the presence of ANY
`Error:` diagnostic line as failure (the plugin's `compile` tool already does).
Both compilers share the diagnostic format
`file(line, col) Error|Warning|Hint|Trace: message`; Nimony additionally emits
`nifmake:` / `FAILURE:` / `niflink` noise that the plugin's Bash hook strips.

## Feature-set differences (Nim 3 direction)

New / changed in Nimony:
- Explicit `nil ref/ptr T` annotations => no null-deref crashes.
- Constrained generics: `proc f[T: SomeConcept](...)`, type-checked generic bodies.
- No forward declarations needed for procs/types.
- Reworked async: `passive` procs + continuations instead of `async`/`await`
  (`await` becomes nothing); `spawn` unified into the event loop.
- New side-effect defaults: `func`/`iterator`/`converter` are `noSideEffect`,
  `proc` is `sideEffect`, with NO inference; override via `.noSideEffect`/`.sideEffect`.
- Accessors are polymorphic instead of `var T` overloading.
- `string` has no terminating zero => no free `cstring` conversion.
- Case sensitive by default; opt into Nim 2 style with `{.feature: "ignoreStyle".}`.
- Macros replaced by compiler plugins (different API); multi-methods removed
  (single-dispatch only); cyclic imports need explicit `{.cyclic.}`.
- New `case`-in-`object` syntax (enables pattern matching).

Currently MISSING / stubbed in Nimony (do not rely on these):
- Nim-compatible exceptions — Nimony uses its own `ErrorCode` enum instead.
- `range` subtype checking — `range[0..10]` is treated as its base `int`.
- Effect system: `tags` ignored, `raises: []` is the default & ignored,
  `gcsafe` ignored.
- Closure iterators.
- Implicit generics (leaving out `[T]` and relying on a type class like `SomeInt`).

Stdlib: Nimony's stdlib is a separate, smaller set under `~/nimony/lib/std/`
(e.g. `echo` lives in `std/syncio`). Don't assume a Nim 2 module or proc exists —
check `lib/std/` and `~/nimony/doc/` (`differences.md`, `stdlib.md`, `language.md`).
