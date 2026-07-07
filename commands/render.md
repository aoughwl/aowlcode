---
description: Render Nimony NIF node(s) as compact pseudo-Nim instead of raw S-expressions.
argument-hint: "<file.nif> [needle]"
---

View the NIF artifact `$ARGUMENTS` as compact pseudo-Nim — roughly 10x smaller
than the raw NIF S-expression stream, and far easier to read.

Steps:

1. Parse `$ARGUMENTS` into the target `.nif` file and an optional `needle`
   (a tag or symbol name to match). NIF artifacts are a Nimony-only concept —
   they live in `nimcache/*.nif`. If given a `.nim` source, point the user at
   `/phase-diff` or `/check` instead.

2. Call the MCP tool **`nimlang.nif_render`** with `{nif_file, needle}` (omit
   `needle` to render the whole artifact's top-level nodes). It returns
   `{rendered:[...]}`, with common tags (proc/var/let/const/call/if/asgn/ret/
   type/…) mapped to Nim-ish syntax and mangled symbols `sym.NN.mod` demangled to
   `sym`. Unknown tags fall back to a raw snippet.

3. Show the rendered pseudo-Nim. Do NOT `cat`/`Read` the raw `.nif` yourself —
   the plugin's hooks block that anyway and steer here; large NIF dumps are
   exactly the token cost this tool avoids. For a structural overview use `/nif`
   (`nif_outline`/`nif_query`) instead.
