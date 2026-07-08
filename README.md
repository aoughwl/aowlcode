# nim-code

A Claude Code plugin that mediates agent access to the **Nim** and **Nimony**
toolchains through structured tools, so an agent works from compact diagnostics,
outlines, and targeted NIF slices instead of raw compiler output and multi‑hundred‑kilobyte
S‑expression artifacts.

The plugin supports both toolchains from a single interface: the same commands
and tools operate on Nim (`nim`, `nimsuggest`, `nimble`) and on
[Nimony](https://github.com/nim-lang/nimony), the NIF‑based Nim reimplementation
(`nimony`, `nimsem`, `hastur`, and the `nimcache/*.nif` artifacts its pipeline
emits). Toolchain selection is automatic and overridable.

## Contents

- [Motivation](#motivation)
- [Installation](#installation)
- [Configuration](#configuration)
- [Toolchain detection](#toolchain-detection)
- [Components](#components)
- [MCP tool reference](#mcp-tool-reference)
- [Terse mode](#terse-mode)
- [Builder mode](#builder-mode)
- [LSP (optional)](#lsp-optional)
- [Hooks](#hooks)
- [Commands](#commands)
- [Skills and subagents](#skills-and-subagents)
- [Examples](#examples)
- [Requirements](#requirements)
- [Design notes](#design-notes)
- [Changelog](#changelog)

## Motivation

Both toolchains produce output that is costly to pass through an agent verbatim.
The plugin targets six recurring sources of token waste:

| Source | Cost | Mitigation |
|--------|------|------------|
| NIF artifacts in `nimcache/` | A single lowered `.nif` is commonly 160 KB–700 KB of parenthesized S‑expression. | NIF is read only through `nif_outline`/`nif_query`/`nif_diff`/`nif_render`; direct reads are intercepted by hooks. |
| Noisy compiler output | `nimony c` / `hastur` interleave `nifmake:`, `FAILURE:`, and `niflink` lines with real diagnostics. | `compile` parses diagnostics; a `PostToolUse` hook strips the noise from ad‑hoc build commands. |
| `nimony c` exits 0 on failure | The exit code is unreliable, so failure is easy to miss. | Failure is determined by parsing for an `Error:` diagnostic, not by exit status. |
| Large NIF test diffs | `hastur --overwrite` diffs embed produced NIF and run to thousands of lines. | `nif_diff` collapses unchanged regions to a structural diff. |
| Symbol lookup across a large tree | Locating a definition and its uses by grep is repetitive and unbounded. | `symbols` (name search) and `defs_uses` (position‑based) return structured results in one call. |
| Repeated context loss | The NIF tag vocabulary and the Nim/Nimony distinction are re‑derived each session. | Shipped as on‑demand skills; a project map is maintained in persistent memory. |

## Installation

The plugin is loaded from this directory; nothing is published to a registry.

Per session:

```bash
claude --plugin-dir /home/savant/nimony-code
```

From the GitHub marketplace (the repo is its own marketplace):

```text
/plugin marketplace add aoughwl/nim-code
/plugin install nim-code@nim-code
```

`nim-code@nim-code` is `<plugin>@<marketplace>`; both are named `nim-code`. A
local checkout works as a marketplace too — `/plugin marketplace add
/home/savant/nimony-code`.

Enabling the plugin auto‑registers the `nimlang` MCP server and activates all
hooks. Run `/reload-plugins` after editing plugin files to reload without
restarting. Commands are namespaced under the plugin — `/nim-code:check`,
`/nim-code:nif`, and so on — and listed by `/help`.

## Configuration

All configuration is via environment variables; none is required.

| Variable | Effect | Default |
|----------|--------|---------|
| `NIMLANG_TOOLCHAIN` | Forces `nim` or `nimony` for every call. | unset (auto‑detect) |
| `NIM_BIN_DIR` | Directory holding `nim`, `nimsuggest`, `nimble`. | `PATH`, then `~/Nim/bin` |
| `NIMONY_BIN_DIR` | Directory holding `nimony`, `nimsem`, `hastur`. | `PATH`, then `~/nimony/bin` |
| `NIMLANG_AGGRESSIVE` | When truthy, every tool defaults to [terse](#terse-mode) output. | unset (verbose) |

Binaries resolve from `PATH` first, then the corresponding directory.

## Toolchain detection

With `toolchain="auto"` (the default on every tool that takes it), the server
walks up from the target file's directory. It selects Nimony if it finds a
`nimony.paths`, a `nimony.cfg`, or a `nim.cfg` referencing nimony; otherwise Nim.
`NIMLANG_TOOLCHAIN` overrides detection globally, and an explicit `toolchain`
argument overrides it per call.

## Components

```
nim-code/                         ${CLAUDE_PLUGIN_ROOT}
├── .claude-plugin/plugin.json    manifest
├── .mcp.json                     registers the `nimlang` MCP server
├── .lsp.json                     optional LSP; routes through scripts/lsp-dispatch.py — see LSP
├── mcp/
│   ├── server.py                 MCP server — stdlib-only Python 3.7, zero dependencies
│   ├── test_server.py            self-test: exercises all tools against live nim/nimony
│   └── README.md                 manual nimsuggest / nimsem fallback notes
├── scripts/
│   ├── lsp-dispatch.py           picks nimlangserver vs nimony-lsp per project
│   └── gen-nif-grammar.py        regenerates skills/nif-format/nif-grammar.md
├── hooks/
│   ├── hooks.json                hook wiring
│   ├── guard-nif-read.py         PreToolUse(Read)  — intercept large .nif reads
│   ├── guard-nif-bash.py         PreToolUse(Bash)  — intercept .nif dumps
│   └── trim-build-output.py      PostToolUse(Bash) — strip build noise
├── commands/                     11 slash commands (see Commands)
├── skills/                       6 skills (see Skills and subagents)
└── agents/                       2 subagents (see Skills and subagents)
```

The `nimlang` MCP server is the core. It speaks JSON‑RPC 2.0 over stdio, shells
out to the appropriate toolchain, and returns one compact structured block per
call. It never returns a whole NIF file.

## MCP tool reference

Fourteen tools are exposed by the `nimlang` server. `compile`, `build`, `outline`,
`defs_uses`, `explain_failure`, `phase_report`, `shrink`, `api`, and `symbols`
support both toolchains; `decl_of` is Nimony‑only. The `nif_*` tools operate on
Nimony NIF artifacts and are Nimony‑only. Every tool accepts `terse` (see
[Terse mode](#terse-mode)). `compile`, `build`, and `defs_uses` also accept
`raw` (see [Builder mode](#builder-mode)).

| Tool | Signature | Result / behavior | Toolchains |
|------|-----------|-------------------|------------|
| `compile` | `(file, toolchain="auto", extra_args=[])` | Type‑checks: runs `nim check` or `nimony c`, parses diagnostics, and reports `ok` by the presence of an `Error:` line rather than the exit code. Returns `{ok, toolchain, stage, diagnostics}`. Does not produce a binary — use `build` for that. | both |
| `build` | `(file, toolchain="auto", run=false, release=false, extra_args=[])` | Produces a linked executable (`nim c` / `nimony c`) with the same structured, noise‑stripped diagnostics, plus the `binary` path (Nim: beside the source; Nimony: `nimcache/<hash>/<module>`). With `run:true`, runs the binary and returns its `{exit_code, output}` separately from diagnostics; `release` adds `-d:release`. | both |
| `outline` | `(file, toolchain="auto")` | Top‑level symbols `{name, kind, line, col}`. Nim via `nimsuggest outline`; Nimony (and the Nim fallback) via a source regex scan. | both |
| `defs_uses` | `(file, line, col, toolchain="auto")` | Definition and uses of the symbol at a position: `{def, uses}`. Nim via `nimsuggest def`/`use`; Nimony via `nimsem --def:FILE,LINE,COL idetools` and `--usages:` against the module's `.s.nif` in `nimcache`. Degrades to `{error, hint}` if the artifact is absent. | both |
| `explain_failure` | `(file, toolchain="auto")` | Compiles and, on failure, returns a short `verdict` and a `culprit`. Nimony extracts the smallest NIF node spanning the error position from the phase artifact; Nim returns ±3 source lines around the first error. Collapses the compile → outline → query sequence into one call. | both |
| `phase_report` | `(file, toolchain="auto")` | Compiles, then summarizes each `nimcache/*.<phase>.nif` (p, s, …) in one line (top tag counts and size), with no raw NIF. Nim returns an empty phase list with a note. | both |
| `shrink` | `(file, toolchain="auto")` | Delta‑debugs a failing file, dropping top‑level statements while the first `Error:` message is preserved. Returns `{original_lines, minimal_lines, minimal_source, kept_error}`. Iteration‑ and time‑bounded. | both |
| `api` | `(module, toolchain="auto", needle=None)` | Typed public API of a module or dependency without reading its source. Nim runs `nim jsondoc` on a `.nim` path, an installed nimble package (e.g. `chroma`), or a stdlib module (e.g. `std/tables`), returning `{name, kind, sig}` entries. For a `.nif`/Nimony target the typed API is the compiled artifact, rendered via `nif_render`. `needle` filters by name substring. | both |
| `symbols` | `(name, root=".", kind=None, uses=false)` | Project‑wide symbol search by name substring; regex‑based and toolchain‑agnostic. Returns `{defs, root}`, and `{uses}` when `uses:true`. Skips `nimcache`, `.git`, `htmldocs`, and nimble dirs; bounded for large trees. | both |
| `decl_of` | `(symbol, cwd=".", kind=None)` | Reverse index: a Nimony symId (`add.0.tgokb0h9q`, as emitted by `defs_uses`/idetools) or a plain name → its declaration site(s) `{sym, name, kind, file, line, col, signature, nif}`, plus `backend`. Prefers the [`niflens`](https://github.com/aoughwl/niflens) helper (the compiler's own NIF libraries — authoritative positions and module‑qualified symIds) and falls back to an in‑Python NIF walk when it is absent. Fills the symId‑keyed gap `symbols` (by name) and `defs_uses` (by position) leave open — for semantic tokens / workspace symbol. | Nimony |
| `nif_outline` | `(nif_file)` | Top‑level `(tag name …)` nodes of a NIF artifact — names only, no bodies. | Nimony |
| `nif_query` | `(nif_file, needle)` | S‑expr subtrees whose head tag or symbol matches `needle`, each snippet truncated, via a paren‑matching scanner. | Nimony |
| `nif_render` | `(nif_file, needle=None)` | Renders NIF node(s) as compact pseudo‑Nim (`proc`/`var`/`let`/`call`/`if`/`type`/… mapped to Nim‑like syntax; `sym.NN.mod` demangled to `sym`), falling back to a raw snippet for unknown tags. Roughly an order of magnitude smaller than raw NIF. | Nimony |
| `nif_diff` | `(file_a, file_b)` | Structural/line diff between two NIF files (unified diff, context 1, unchanged regions collapsed). | Nimony |

## Terse mode

Every tool accepts an optional `terse` boolean, defaulting to the truthiness of
`NIMLANG_AGGRESSIVE`. Terse output collapses to the smallest useful shape and
drops warnings and hints; verbose shapes are unchanged, so the flag is
back‑compatible and opt‑in.

| Tool | Terse shape |
|------|-------------|
| `compile` | `diagnostics` become `"file:line:col msg"` strings; warnings/hints dropped; `ok` kept. |
| `outline` | `["name:line", …]` |
| `defs_uses` | `{def: "file:line" \| null, uses: ["file:line", …]}` |
| `symbols` | `{defs: ["file:line kind name", …], uses: ["file:line", …]}` |
| `api` | `api` becomes a list of bare signature strings. |
| `nif_query` / `nif_outline` / `nif_render` | Tighter per‑snippet caps (~15 lines); null fields omitted. |

`/aggressive [on|off]` documents enabling terse mode and its trade‑offs.

## Builder mode

`compile`, `build`, and `defs_uses` accept an optional `raw` boolean. The tools
normally *hide* the low‑level toolchain contracts (path handling, exit‑code‑0‑
on‑error, coordinate bases) — which is what you want when reading or debugging,
but exactly what you must reproduce when **building a competing consumer** of the
compiler (an LSP, a formatter, a custom driver). With `raw:true` a tool also
returns the exact argv it ran, so you can copy a known‑good invocation:

- `compile` / `build` → `invocation` (the full `nim`/`nimony` command line).
- `defs_uses` → `invocations` (the `nimsem …idetools` / `nimsuggest` commands)
  plus `contract`, spelling out the gotcha the tool otherwise absorbs — notably
  that idetools' tracked path must be the **cwd‑relative / basename** form stored
  in the `.s.nif`, never an absolute path (which fails with *"symbol not found"*).

The [`compiler-contracts`](skills/compiler-contracts/SKILL.md) skill collects
these contracts, and [`nif-format/nif-grammar.md`](skills/nif-format/nif-grammar.md)
— generated from the compiler source by `scripts/gen-nif-grammar.py` — is the
parser‑grade NIF schema (decl‑kind classes, child‑slot layouts, `fld`/`efld`
nesting) that the rendered‑output tools do not give.

## LSP (optional)

Claude Code consumes a language server as a first‑class capability: after each
edit to a mapped file it injects type errors into context automatically (no
separate build step), and the agent can call it for go‑to‑definition,
find‑references, hover types, and workspace symbol search — backed by a
persistent index, so results are more precise than the per‑call
`nimsuggest`/regex paths the MCP tools use. The LSP and the MCP tools are
complementary: the LSP closes the edit → error loop automatically, while the
MCP tools provide the NIF‑aware and dependency‑API operations an LSP does not.

The LSP is an **optional enhancement, not part of the baseline** — the MCP layer
remains the both‑toolchains, zero‑dependency core, and every tool, hook,
command, and skill works without any LSP installed. Auto‑diagnostics are on
(`"diagnostics": true`); set it to `false` in `.lsp.json` to keep navigation but
suppress the per‑edit injection.

### One entry, per‑project auto‑selection

Nim and Nimony share the `.nim` extension, `.lsp.json` routes servers by
extension, and Claude Code has no documented way to disambiguate two servers
claiming the same one — running both at once would double‑diagnose every file,
each server choking on the other language. Its only documented LSP surface is a
plugin's own `.lsp.json`; there is no supported project‑level LSP override or
per‑server `disabled` flag.

So `.lsp.json` ships a **single** entry whose command is a dispatcher,
[`scripts/lsp-dispatch.py`](scripts/lsp-dispatch.py) (stdlib‑only Python 3):

```json
{
  "nim-code": {
    "command": "python3",
    "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/lsp-dispatch.py"],
    "extensionToLanguage": { ".nim": "nim", ".nims": "nim" },
    "diagnostics": true
  }
}
```

On launch the dispatcher applies the **same toolchain detection as the MCP
server** — walk up from the workspace for a `nimony.paths`/`nimony.cfg` (or a
`nim.cfg` naming nimony); `NIMLANG_TOOLCHAIN=nim|nimony` forces it — then
`exec`s exactly one real server, passing the JSON‑RPC stdio through untouched:

| Detected | Server | Install |
|----------|--------|---------|
| Nim (default) | [`nimlangserver`](https://github.com/nim-lang/langserver) | `nimble install nimlangserver` |
| Nimony | [`aoughwl/nimony-lsp`](https://github.com/aoughwl/nimony-lsp) | build `server/` → put `nimony-lsp` on `PATH` |

Because only one server is ever started, the same‑extension hazard never
arises, and no per‑project configuration is required. Overrides (all optional
env): `NIMONY_LSP` / `NIM_LANGSERVER` point at the server binaries; `NIMONY_EXE`
sets the Nimony compiler the LSP shells out to (the dispatcher auto‑fills it
from the `nimony` on `PATH`). If the selected server is not installed, the
dispatcher exits with a one‑line reason in the `/plugin` **Errors** tab and
nothing else is affected.

`nimony-lsp` is verified working end‑to‑end against `nimony` 0.4.0 —
diagnostics, goto‑definition, find‑references, hover, and document symbols all
respond (completion is advertised). A Nimony project without the LSP loses
nothing else: navigation and diagnostics stay on the MCP tools (`compile`,
`defs_uses`, `symbols`, the `nif_*` family), which are the only path an LSP does
not cover for Nimony's NIF pipeline.

## Hooks

Three hooks keep raw output out of the context window without agent involvement.
All are stdlib‑only Python and fail open (any error exits 0, never blocking the
tool).

| Hook | Event / matcher | Behavior |
|------|-----------------|----------|
| `guard-nif-read.py` | PreToolUse / `Read` | Denies reading a `.nif` over 15 KB, and attaches a compact `nif_outline` of the file to the denial reason so the agent receives the useful form in the same turn. |
| `guard-nif-bash.py` | PreToolUse / `Bash` | Denies `cat`/`head`/`tail`/`less`/`more`/`bat` targeting a `.nif` over 15 KB — the shell path around the `Read` guard — and points to the NIF tools. No‑op otherwise. |
| `trim-build-output.py` | PostToolUse / `Bash` | For `nimony`/`hastur`/`nim c`/`nimble` commands, strips `nifmake:`/`FAILURE:`/`niflink` lines and surfaces the diagnostics as additional context. No‑op otherwise. |

The `Read` hook illustrates the plugin's preferred pattern: rather than only
blocking a wasteful action, it supplies the cheap alternative in the same
response.

## Commands

| Command | Tool | Purpose |
|---------|------|---------|
| `/check [file]` | `compile` | Type‑check and report structured diagnostics. |
| `/build [file] [run] [release]` | `build` | Build a linked executable; report diagnostics, the binary path, and optional run output. |
| `/explain-failure [file]` | `explain_failure` | One‑call "why did this fail," with the culprit. |
| `/shrink [file]` | `shrink` | Minimal still‑failing reproduction. |
| `/api <module> [needle]` | `api` | Typed API of a module or dependency. |
| `/symbols <name>` | `symbols` | Project‑wide symbol search. |
| `/nif <file.nif> [needle]` | `nif_outline` / `nif_query` | Outline or query a NIF artifact. |
| `/render <file.nif> [needle]` | `nif_render` | Pseudo‑Nim view of a NIF node. |
| `/phase-diff <file.nim>` | `nif_diff` | Diff a file's NIF phase artifacts. |
| `/nimony-bug [file]` | — | Run the Nimony compiler debug loop and report only diagnostics. |
| `/aggressive [on\|off]` | — | Explain and toggle terse mode. |

## Skills and subagents

Skills load on demand; subagents run in their own context and return only a
conclusion.

| Skill | Purpose |
|-------|---------|
| `nif-format` | Condensed NIF tag vocabulary and the nifler → nimony → hexer → lengc pipeline; points to `doc/tags.md` for the long tail, and to the generated `nif-grammar.md` for the parser‑grade schema. |
| `compiler-contracts` | The low‑level toolchain contracts for BUILDING on the compiler (LSP, formatter, custom driver): idetools relative‑path rule, exit‑code‑0, coordinate bases, NIF decl‑vs‑use and line‑info encoding. Pairs with `raw` mode. |
| `nim-vs-nimony` | Feature‑set and toolchain differences; which binary handles what. |
| `debug-loop` | The `AGENTS.md` compiler debug workflow (build → bug → nimcache diff → rep → `--overwrite`). |
| `token-thrift` | Prefer recipe tools and terse mode; never dump a `.nif`; offload fix loops to `nim-fixer`. |
| `repo-map` | Maintain a lazy, incremental `project-map` in file‑memory (one line per touched file); prefer `symbols`/`api` over grep/reads; persist non‑obvious toolchain facts. |

| Subagent | Model | Purpose |
|----------|-------|---------|
| `nif-inspector` | default | Heavy NIF and phase‑artifact reading in an isolated context; returns only the conclusion. |
| `nim-fixer` | `haiku` | Runs the compile → shrink → explain → edit → recompile loop in its own context and returns only the final diff and a verdict. |

## Examples

The same command works across both toolchains and returns the same diagnostic
shape.

### Nim

`greeter.nim`:

```nim
proc greet(name: string) =
  echo "hi ", nam   # typo: `nam`
```

`/check greeter.nim` detects Nim, runs `nim check`, and returns:

```json
{
  "ok": false,
  "toolchain": "nim",
  "stage": "check",
  "diagnostics": [
    { "file": "greeter.nim", "line": 2, "col": 18,
      "severity": "Error", "message": "undeclared identifier: 'nam'" }
  ]
}
```

### Nimony

`hello.nim`, in a project whose `nimony.cfg`/`nimony.paths` selects Nimony:

```nim
import std/syncio

echo "hello, world
```

`/check hello.nim` detects Nimony, runs `nimony c`, strips the build chatter,
and reports failure despite `nimony c` exiting 0, because an `Error:` line was
parsed:

```json
{
  "ok": false,
  "toolchain": "nimony",
  "stage": "c",
  "diagnostics": [
    { "file": "hello.nim", "line": 3, "col": 6,
      "severity": "Error", "message": "closing \" expected" }
  ]
}
```

## Requirements

- **python3** 3.7+, standard library only. The MCP server and hooks have no
  third‑party dependencies.
- **Nim** — `nim` and `nimsuggest` (e.g. `~/Nim/bin`). Required for the Nim side
  of `compile`, `outline`, `defs_uses`, and for `api` (`nim jsondoc`).
- **Nimony** — `nimony`, `nimsem`, `hastur` (e.g. `~/nimony/bin`, built with
  `nim c -r src/hastur build all`). Required for the Nimony side of every tool
  and for all `nif_*` tools.

`mcp/test_server.py` starts the server and exercises all fourteen tools against
live `nim` and `nimony` compiles; run it to verify the environment.

The optional [`niflens`](https://github.com/aoughwl/niflens) helper (a Nim CLI
over Nimony's own NIF libraries) is preferred by `decl_of` when on `PATH` (or
`$NIFLENS`); without it, `decl_of` falls back to the in‑Python NIF walk. Build
it with `NIMONY_SRC=<nimony checkout> nimble build` and put `bin/niflens` on
`PATH`. Not required for any other tool.

The optional LSP additionally needs a language server on `PATH` —
**nimlangserver** (`nimble install nimlangserver`) for Nim and/or
**nimony-lsp** ([aoughwl/nimony-lsp](https://github.com/aoughwl/nimony-lsp)) for
Nimony; the dispatcher picks per project. See [LSP](#lsp-optional). Neither is
required for any MCP tool, hook, command, or skill.

## Design notes

- **Zero dependencies.** The server and hooks are stdlib‑only Python 3.7, so the
  plugin runs wherever `python3` and the toolchains are present, with no install
  step.
- **Server‑side orchestration.** `explain_failure` and `phase_report` run a
  multi‑step workflow inside one call and return only the conclusion, keeping the
  intermediate output out of the transcript.
- **Fail open.** Hooks and best‑effort tool paths degrade to a plain message or a
  structured `{error, hint}` rather than blocking the agent or crashing a tool.
- **Both toolchains, one interface.** Detection, binary resolution, a shared
  diagnostic grammar, and a common result shape mean the same commands serve Nim
  and Nimony without the agent tracking which is in use.

## Changelog

- **0.5** — `decl_of` now prefers the [`niflens`](https://github.com/aoughwl/niflens)
  helper — a Nim CLI over Nimony's own NIF libraries (`nifreader`/`nifstreams`/
  `nifcursors`) — for authoritative line info and module‑qualified symIds,
  falling back to the in‑Python NIF walk when it is absent (reported as
  `backend`). This is the first step of moving NIF *parsing* off the regex
  fallback onto the compiler's real libraries via a subprocess, while the Python
  server stays the zero‑install orchestration layer; the same core is intended
  to back a Nimony LSP and a persistent NIF daemon.
- **0.4** — Builder‑mode additions for consumers reimplementing the toolchain
  (feedback from building `nimony-lsp`): `decl_of` reverse‑index tool (symId →
  declaration site from the `.s.nif`); `raw` mode on `compile`/`build`/
  `defs_uses` that echoes the exact argv and surfaces the idetools relative‑path
  contract the tools otherwise hide; a generated parser‑grade
  `skills/nif-format/nif-grammar.md` (`scripts/gen-nif-grammar.py`) with
  decl‑kind classes and child‑slot layouts; and a `compiler-contracts` skill.
- **0.3** — LSP is now a single auto‑dispatching `.lsp.json` entry
  (`scripts/lsp-dispatch.py`): it applies the plugin's toolchain detection per
  project and `exec`s `nimlangserver` for Nim or `nimony-lsp` for Nimony,
  launching exactly one server so the shared‑`.nim` collision cannot arise.
  Replaces the earlier Nim‑only entry plus the unsupported project‑settings
  opt‑in. `nimony-lsp` ([aoughwl/nimony-lsp](https://github.com/aoughwl/nimony-lsp))
  verified against `nimony` 0.4.0 (diagnostics, goto‑def, find‑refs, hover,
  document symbols).
- **0.2** — Terse mode on all tools (`NIMLANG_AGGRESSIVE`); `explain_failure`,
  `phase_report`, `nif_render`, `shrink`, `api`, `symbols`; `guard-nif-bash`
  hook and the transform‑not‑block upgrade to `guard-nif-read`; `nim-fixer`
  subagent; `token-thrift` and `repo-map` skills; installable as a marketplace;
  optional Nim LSP via `.lsp.json` (`nimlangserver`). `build` tool/`/build`
  command for producing a linked executable with structured diagnostics.
- **0.1** — `nimlang` MCP server (`compile`, `outline`, `nif_outline`,
  `nif_query`, `nif_diff`, `defs_uses`); `guard-nif-read` and
  `trim-build-output` hooks; `nif-inspector` subagent; `nif-format`,
  `nim-vs-nimony`, `debug-loop` skills.
