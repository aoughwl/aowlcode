---
name: compiler-contracts
description: >-
  Read this when BUILDING TOOLING on top of the Nim/Nimony toolchain — an LSP,
  a formatter, a custom driver, a NIF parser — rather than just fixing a bug.
  It lists the low-level compiler contracts the MCP tools normally handle for
  you (and therefore hide): the idetools relative-path rule, exit-code-0-on-
  error, coordinate bases, NIF decl-vs-use and line-info encoding, and where
  binaries land. Pair with the raw mode of compile/build/defs_uses.
---

# Compiler contracts (for building a competing consumer)

The `aowlcode` MCP tools are tuned for *reading and debugging* Nimony/Nim: they
handle these contracts internally so a caller never sees them. If you are
instead **reimplementing a consumer of the same toolchain**, the conveniences
hide exactly the invariants you must reproduce. This is the checklist.

Tip: pass `raw: true` to `compile`, `build`, and `defs_uses` — they then echo
the exact argv they ran (and `defs_uses` echoes the relevant contract), so you
can copy a known-good invocation instead of reverse-engineering one.

## idetools (goto-def / find-usages)

- Command: `nimsem --def:FILE,LINE,COL idetools MODULE.s.nif` (or `--usages:`).
  It is **`--def:` / `--usages:`, not `--track`.**
- **The tracked `FILE` must be the path as stored in the `.s.nif` — the
  cwd-relative / basename form (e.g. `good.nim`), NOT an absolute path.** An
  absolute path fails with `"symbol not found"` and nothing else. Run `nimsem`
  from the file's directory. *(This is the single hardest gotcha when writing a
  Nimony LSP; the plugin's `defs_uses` hides it.)*
- Coordinate bases: **input** `LINE,COL` are **1-based**. **Output** records are
  tab-separated `kind \t … \t symId \t … \t file \t line \t col` with **line
  1-based, col 0-based**. For Nim (`nimsuggest`) def/use is `SECTION file:line:col`
  over `--stdin`, 1-based in, reply cols 5/6/7 (file/line/col, col 0-based).

## Exit codes

- **`nimony c` / `nimsem` exit 0 even on error.** Never branch on the exit code.
  Treat the presence of any `path(line, col) Error:` line on stdout as failure.
  `Trace:` lines are related-info of the preceding `Error:`. (`nim check` *does*
  set a non-zero code, but still parse for `Error:` — it is the common path.)
- Diagnostic format is `path(line, col) Kind: message`, **line and col 1-based**.
- Strip build-driver noise before showing diagnostics: lines beginning
  `nifmake:`, `FAILURE:`, or from `niflink` are not diagnostics.

## NIF artifacts

- `:name` (a leading colon = `SymbolDef`) is a **declaration**; a bare `name`
  (`Symbol`) is a **use**. This one distinction gives goto-def / find-refs /
  "where declared" almost for free — walk `:`-prefixed tokens.
- `.` is the empty/omitted slot (`DotToken`), not a symbol.
- **Line info is a base62 delta** carried as a suffix on a token: `@col,line,file`
  where each part is optional and a leading `~` means a negative delta. The
  delta is relative to the enclosing parent node; accumulate down the tree to
  get an absolute `(file, line, col)` (col 0-based in the stream). See
  `nifreader.nim:handleLineInfo` for the canonical decoder; the plugin's
  `nif_forms_with_pos` (in `mcp/server.py`) is a Python port.
- Decl-kind equivalence classes and the fixed child-slot layout of every
  declaration family (which child index is the return type, the body, the
  fields; `fld` vs `efld`; that `let/glet/tlet/gvar/tvar/var/const/cursor` are
  all variable-like) are in **`skills/nif-format/nif-grammar.md`**, generated
  from the compiler source — the authoritative schema the rendered-output tools
  do not give.

## Build outputs

- `nim c <mod>.nim` → executable **beside the source**, named `<mod>`.
- `nimony c <mod>.nim` → executable under **`nimcache/<hash>/<mod>`** (not beside
  the source). `build` with `raw: true` reports the located path.
- Pipeline: `nifler` (`.p.nif`) → `nimony`/`nimsem` (`.s.nif` + interface index
  `.s.idx.nif`) → `hexer` (`.x.nif`/`.dce.nif`) → `lengc` → C. `nifmake` is the
  Tup-style incremental driver; the `.s.idx.nif` interface checksum + mtime
  preservation is what makes importer rebuilds skip.

## Reverse lookups

- `decl_of(symbol)` resolves a symId (or plain name) → declaration site(s)
  `{sym, kind, file, line, col, signature}` across nimcache — the symId-keyed
  query that `symbols` (by name) and `defs_uses` (by position) do not cover.
