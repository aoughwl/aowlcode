---
description: Outline or query a Nimony NIF artifact without dumping the whole file.
argument-hint: "<file.nif> [needle]"
---

Inspect the NIF artifact at the first token of `$ARGUMENTS`. NIF files are large
S-expression IR streams — never read them raw (the plugin's Read hook blocks
that for files > 15000 bytes). Use the MCP tools instead.

Steps:

1. Parse `$ARGUMENTS` as `<file.nif> [needle]`.

2. If a `needle` is given, call **`nimlang.nif_query`** with `{nif_file, needle}`.
   It returns `{matches:[{tag,name,snippet}]}` — only the S-expr subtrees whose
   head tag or symbol matches, each snippet truncated (~40 lines). Summarize the
   matches; quote a snippet only when the exact text matters.

3. If no `needle`, call **`nimlang.nif_outline`** with `{nif_file}`. It returns
   `{tags:[{tag,name,line}]}` — the top-level `(tag name ...)` nodes only, no
   bodies. Present a compact outline (tag, name, line).

4. If the artifact is heavy or the task needs several queries, delegate to the
   `nif-inspector` subagent so the bulky reads stay out of this context.

Reference: the `nif-format` skill for the tag vocabulary, and
`~/nimony/doc/tags.md` for the long tail. NIF phase suffixes:
`.p.nif` (parsed, nifler) -> `.s.nif` (semchecked, nimony) ->
`.x.nif` / `.dce.nif` (hexer lowering) -> Leng/C. Use `/phase-diff` to compare
adjacent phases.
