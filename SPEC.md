# aowlcode — Claude Code plugin SPEC (shared contract)

A Claude Code plugin that makes agent work on **Nim** AND **Nimony** codebases
token-efficient. Everything below is the contract all pieces build against.
Repo root = `/home/savant/nimony-code` = `${CLAUDE_PLUGIN_ROOT}`.

## Toolchains (BOTH must be supported everywhere)

| Concept        | Nim                              | Nimony                                    |
|----------------|----------------------------------|-------------------------------------------|
| compiler bin   | `nim` (~/Nim/bin)                | `nimony` (~/nimony/bin)                    |
| check errors   | `nim check --hints:off --colors:off FILE` | `nimony c FILE` (strip nifmake noise) |
| def/uses       | `nimsuggest --stdin` (`def`/`use`/`outline`) | `nimsem idetools --track ...`  |
| IR artifacts   | (none)                           | `nimcache/*.nif` (NIF S-expr streams)     |
| test/build     | `nimble` / `nim c`               | `hastur` (build/test/bug/rep)             |

**Shared diagnostic format** (identical for both): a line matching
`^(?P<file>.+?)\((?P<line>\d+),\s*(?P<col>\d+)\)\s+(?P<sev>Error|Warning|Hint|Trace):\s*(?P<msg>.*)$`
Nimony also emits noise lines starting with `nifmake:`, `FAILURE:`, `niflink` — strip these.
IMPORTANT: `nimony c` may exit 0 even on failure — treat presence of any `Error:` line as failure.

**Toolchain auto-detection** (`toolchain="auto"` default): walk up from the target
file; if a `nimony.paths`, `nimony.cfg`, or `nim.cfg` mentioning nimony is found, use
nimony; else use `nim`. Always allow explicit override `toolchain: "nim" | "nimony"`.
Also honor env var `NIMLANG_TOOLCHAIN`.

## MCP server  (mcp/server.py — Python 3.7, STDLIB ONLY, no walrus `:=`, no f-string `=`)

Zero-dependency JSON-RPC 2.0 over stdio implementing MCP: handle `initialize`,
`notifications/initialized`, `tools/list`, `tools/call`. Shell out to the binaries
above via `subprocess`. Every tool returns a single compact `text` content block
(JSON where structured). Never dump whole NIF files. Bin paths: resolve from PATH,
fall back to `~/Nim/bin` and `~/nimony/bin`. Configurable via env
`NIM_BIN_DIR`, `NIMONY_BIN_DIR`.

Tools (names are the contract — hooks/commands/README reference these):

1. `compile(file, toolchain="auto", extra_args=[])`
   → `{ok, toolchain, stage, diagnostics:[{file,line,col,severity,message}]}`
   Runs the right checker, parses diagnostics, correct ok/fail. Timeout ~120s.

2. `outline(file, toolchain="auto")`
   → `{toolchain, symbols:[{name,kind,line,col}]}`
   Nim: `nimsuggest --stdin` `outline FILE`; fallback = regex scan for
   `proc/func/method/template/macro/type/const/var/let/iterator`.
   Nimony: same regex fallback on the .nim source (nimsuggest is Nim-only).

3. `nif_outline(nif_file)`  (Nimony artifacts only)
   → `{tags:[{tag,name,line}]}` — top-level `(tag name ...)` nodes only, no bodies.

4. `nif_query(nif_file, needle)`  → `{matches:[{tag,name,snippet}]}`
   Return only S-expr subtrees whose head tag or symbol matches `needle`.
   Truncate each snippet to ~40 lines. Use a tiny paren-matching scanner.

5. `nif_diff(file_a, file_b)` → `{changed:[...]}` compact structural/line diff,
   collapsing unchanged regions (difflib unified diff, context=1, header-trimmed).

6. `defs_uses(file, line, col, toolchain="auto")`
   → `{def:{file,line,col}|null, uses:[{file,line,col}]}`
   Nim: nimsuggest `def`/`use`. Nimony: `nimsem idetools --track FILE,line,col` on the
   `.s.nif` in nimcache (best-effort; degrade to `{error, hint}` if unavailable).

Must ship `mcp/test_server.py` (or a shell test) that starts the server, calls
`compile` on a bad Nim file AND a bad Nimony file, and asserts diagnostics parse.
Provide a `mcp/README.md` note on manual `nimsuggest`/`idetools` fallbacks.

## Hooks (hooks/hooks.json + scripts, python3, stdlib only)

- `guard-nif-read.py` — **PreToolUse** on `Read`. Read hook JSON from stdin. If
  `tool_input.file_path` ends in `.nif` and file size > 15000 bytes, deny with a
  message steering to the `nif_outline`/`nif_query` MCP tools (and `/nif`). Output the
  documented PreToolUse decision JSON (`hookSpecificOutput.permissionDecision:"deny"`).
  Otherwise allow (exit 0, no output).
- `trim-build-output.py` — **PostToolUse** on `Bash`. If the command invoked
  `nimony`/`hastur`/`nim c`/`nimble`, strip `nifmake:`/`FAILURE:`/`niflink` noise lines
  from output and surface just diagnostics as `hookSpecificOutput.additionalContext`.
  Be a no-op for unrelated commands. Never crash the tool (always exit 0).

Reference scripts with `${CLAUDE_PLUGIN_ROOT}/hooks/...`.

## Commands (commands/*.md — frontmatter: `description`, `argument-hint`)

- `check.md` `/check [file]` — compile via MCP `compile`, works for Nim & Nimony.
- `nif.md` `/nif <file.nif> [needle]` — outline or query a NIF artifact.
- `phase-diff.md` `/phase-diff <file.nim>` — compile with nimony, diff the phase
  artifacts in nimcache (p → s → …) using `nif_diff`.
- `nimony-bug.md` `/nimony-bug [file]` — run the AGENTS.md debug loop (build nimony,
  `hastur bug`, inspect nimcache) and report only structured diagnostics.

## Subagent (agents/nif-inspector.md)

Frontmatter `name`, `description` (auto-delegate on "inspect/hunt NIF / phase
artifacts"), `tools`. Does heavy NIF reading in its own context, returns only the
conclusion. Must mention it handles both Nim source and Nimony NIF.

## Skills (skills/<name>/SKILL.md — frontmatter `name`, `description`)

- `nif-format` — condensed NIF tag vocab + phase pipeline (nifler→nimony→hexer→lengc);
  point to ~/nimony/doc/tags.md for the long tail.
- `nim-vs-nimony` — feature-set + toolchain differences; which binary for what;
  "don't assume Nim 2's feature set."
- `debug-loop` — the ~/nimony/AGENTS.md workflow (build → bug → nimcache diff → rep →
  `hastur --overwrite`); assume nifler/nifmake/lengc stable, suspect nimony/hexer.

## plugin.json (`.claude-plugin/plugin.json`) + `.mcp.json`

Manifest: name `aowlcode`, version `0.1.0`, description, author `savannt`.
`.mcp.json` registers the MCP server:
`{"mcpServers":{"nimlang":{"command":"python3","args":["${CLAUDE_PLUGIN_ROOT}/mcp/server.py"]}}}`
`hooks/hooks.json` wires the two hooks.

## README.md

Explain the problem (NIF/verbose output token cost), the architecture, the full tool
list, install instructions (`/plugin` marketplace or `claude --plugin-dir`), and a
"works for both Nim and Nimony" section with examples for each.

---

# v0.2 — Aggressive token-saving layer (BOTH Nim & Nimony)

## Terse mode (applies to ALL tools, old and new)
Every tool accepts optional `terse: bool`. Default = truthy env `NIMLANG_AGGRESSIVE`.
When terse:
- `compile` → drop Warning/Hint, diagnostics become `["file:line:col msg", ...]`, keep `ok`.
- `outline` → `["name:line", ...]`.
- `defs_uses` → `{def:"file:line"|null, uses:["file:line", ...]}`.
- `nif_query`/`nif_outline`/`nif_render` → tighter caps (~15 lines/snippet), no null fields.
Non-terse output shapes are unchanged (back-compat).

## New MCP tools
7. `explain_failure(file, toolchain="auto", terse=...)`
   → `{ok, toolchain, verdict, diagnostics, culprit?}`. Compile; on failure produce a
   ≤5-line `verdict`. Nimony: locate the phase artifact for the failing file and extract
   the smallest NIF node spanning the error position into `culprit` (use nif scanner).
   Nim: put ±3 source lines around the first error into `culprit`. One call replaces
   compile→list→outline→query.
8. `phase_report(file, toolchain="auto", terse=...)`
   → `{ok, phases:[{phase, artifact, summary}]}`. Nimony: compile, then for each
   `nimcache/*.<phase>.nif` (p, s, …) give a 1-line summary (top tag counts + size),
   NO raw NIF. Nim: `{ok, phases:[], note:"Nim C backend has no NIF phases"}` + compile.
9. `nif_render(nif_file, needle=None, terse=...)`  (Nimony only)
   → `{rendered:[...]}`. Render matching NIF node(s) as compact **pseudo-Nim**
   (map common tags proc/var/let/const/call/if/asgn/ret/type/… to Nim-ish syntax;
   demangle `sym.NN.mod` → `sym`). Fall back to raw snippet for unknown tags. ~10x
   smaller than raw NIF.
10. `shrink(file, toolchain="auto")`
    → `{original_lines, minimal_lines, minimal_source, kept_error}`. Delta-debug: iteratively
    drop top-level statements/lines while the FIRST `Error:` message is preserved; return
    the minimal still-failing source. Works for both toolchains. Bound iterations/time.

Update `mcp/test_server.py` to cover explain_failure (Nim+Nimony), shrink, terse mode,
and nif_render. Keep all existing checks green.

## New / upgraded hooks
- UPGRADE `guard-nif-read.py`: on a big `.nif` Read, still deny, but RUN `nif_outline`
  (import from server, or shell `python3 server.py`-free helper) and embed the compact
  outline in `permissionDecisionReason` so the model gets the useful version same-turn
  ("transform-not-block"). Never crash → fall back to the plain deny message.
- NEW `guard-nif-bash.py` — **PreToolUse** on `Bash`. If the command is `cat/head/tail/
  less/more/bat` targeting a `.nif` path >15000 bytes, deny and steer to `nif_outline`/
  `nif_query`/`nif_render`/`/nif`. No-op otherwise. Wire in hooks.json.

## New commands
- `explain-failure.md` `/explain-failure [file]` → MCP `explain_failure`.
- `shrink.md` `/shrink [file]` → MCP `shrink`, show minimal repro.
- `render.md` `/render <file.nif> [needle]` → MCP `nif_render`.
- `aggressive.md` `/aggressive [on|off]` → explain enabling terse mode (env
  `NIMLANG_AGGRESSIVE=1`) and per-call `terse:true`; note the trade-offs.

## New subagent
- `agents/nim-fixer.md` — frontmatter `name`, `description` (auto-delegate on
  "fix/iterate on a failing Nim/Nimony compile"), `tools`, `model: haiku` (cheap grunt).
  Runs the compile→shrink→explain→edit→recompile loop entirely in its own context and
  returns ONLY the final diff + verdict, keeping verbose output out of the main thread.

## New skill
- `skills/token-thrift/SKILL.md` — tells the agent: prefer recipe tools
  (`explain_failure`/`phase_report`) over manual multi-call sequences, enable terse mode,
  never `cat` a `.nif`, offload verbose fix loops to the `nim-fixer` subagent.

## Docs
Update README.md with an "Aggressive mode (v0.2)" section: terse flag, the 4 new tools,
the new hook + command + subagent, and the "beyond MCP" plugin features (hooks that
transform-not-block, cheap-model subagents, token-thrift skill).
