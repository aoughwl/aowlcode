# aowlcode

A Claude Code plugin + MCP server that mediates agent access to the **Nim** and
**Nimony** toolchains through structured tools — so an agent works from compact
diagnostics, outlines, and targeted NIF slices instead of raw compiler output and
multi-hundred-kilobyte S-expression artifacts.

**📖 Full docs → [aoughwl.github.io/docs/aowlcode](https://aoughwl.github.io/docs/aowlcode)**

```bash
claude --plugin-dir /path/to/aowlcode
```

- One interface over both toolchains (`nim`/`nimsuggest`/`nimble` and
  `nimony`/`nimsem`/`hastur`), auto-detected.
- Structured tools: `compile`, `build`, `outline`, `symbols`, `defs_uses`,
  `nif_outline`/`nif_query`/`nif_diff`/`nif_render`, `explain_failure`, `shrink`, …
- Hooks strip build noise and intercept raw NIF reads; NIF format + phase pipeline
  shipped as on-demand skills.
