---
description: Toggle aggressive terse mode for the nimlang MCP tools (compact file:line output).
argument-hint: "[on|off]"
---

Explain and help toggle **aggressive (terse) mode** for the `nimlang` MCP
server. This does not run a tool itself — it configures how every `nimlang` tool
formats output. Interpret `$ARGUMENTS` (`on`, `off`, or empty = explain current
state and both options).

## What terse mode does

Every `nimlang` tool accepts an optional `terse: bool`, defaulting to the
truthiness of the `NIMLANG_AGGRESSIVE` env var. When terse:

- `compile` / `explain_failure` — drop Warning/Hint diagnostics; each becomes a
  single `"file:line:col msg"` string; `ok` is kept.
- `outline` — `["name:line", ...]`.
- `defs_uses` — `{def:"file:line"|null, uses:["file:line", ...]}`.
- `nif_query` / `nif_outline` / `nif_render` — tighter snippet caps (~15 lines),
  null fields dropped.

The trade-off: much smaller, `file:line`-style output, but warnings and hints
are dropped and snippets are truncated harder. Non-terse (default) output shapes
are unchanged, so turn it off when you need full diagnostics.

## Turning it ON

- **Whole session (all tools, all calls):** set the env var before/when launching
  Claude Code so the MCP server inherits it — `export NIMLANG_AGGRESSIVE=1`. This
  affects the entire `nimlang` server for the session.
- **One call:** pass `terse: true` in the arguments to any individual `nimlang`
  tool call, no env change needed.

## Turning it OFF

- Per call: pass `terse: false` (explicitly overrides the env default).
- Whole session: unset the env var (`unset NIMLANG_AGGRESSIVE`, or set it to an
  empty/falsy value) and restart the MCP server so it no longer defaults to terse.

If `$ARGUMENTS` is `on`/`off`, tell the user the exact step for their case
(env var for the session vs. `terse:` per call) rather than trying to mutate a
running server's environment yourself.
