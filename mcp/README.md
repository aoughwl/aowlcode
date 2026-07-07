# nimlang MCP server

Zero-dependency (Python 3.7, stdlib only) JSON-RPC 2.0 MCP server over stdio.
It gives Claude token-efficient, structured access to **Nim** and **Nimony**
toolchains so the agent never has to read raw compiler spew or whole `.nif`
files.

Registered by the plugin's `.mcp.json` as:

```json
{"mcpServers":{"nimlang":{"command":"python3","args":["${CLAUDE_PLUGIN_ROOT}/mcp/server.py"]}}}
```

## Toolchain handling

- **auto-detect** (default): walk up from the target file; if a `nimony.paths`,
  `nimony.cfg`, or a `nim.cfg` mentioning `nimony` is found, use **nimony**,
  otherwise **nim**.
- Force per call with `toolchain: "nim" | "nimony"`.
- Or globally via env `NIMLANG_TOOLCHAIN=nim|nimony`.

Binaries are resolved from `PATH`, then `~/Nim/bin` (Nim) and `~/nimony/bin`
(Nimony). Override the directories with `NIM_BIN_DIR` / `NIMONY_BIN_DIR`.

## Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `compile(file, toolchain="auto", extra_args=[])` | Type-check via `nim check --hints:off --colors:off` or `nimony c`. Nimony's `nifmake:`/`FAILURE:`/`niflink` noise is stripped; because `nimony c` can exit 0 on failure, any `Error:` line means failure. | `{ok, toolchain, stage, diagnostics:[{file,line,col,severity,message}]}` |
| `outline(file, toolchain="auto")` | Top-level symbols. Nim uses `nimsuggest outline`; falls back to a regex scan. Nimony always uses the regex scan (nimsuggest is Nim-only). | `{toolchain, symbols:[{name,kind,line,col}], source?}` |
| `nif_outline(nif_file)` | Top-level `(tag name ...)` nodes of a NIF artifact, no bodies. | `{tags:[{tag,name,line}]}` |
| `nif_query(nif_file, needle)` | Only the NIF subtrees whose head tag or symbol matches `needle`; snippets truncated to ~40 lines. | `{matches:[{tag,name,snippet}], count}` |
| `nif_diff(file_a, file_b)` | Compact unified diff (context=1, header trimmed) collapsing unchanged regions. | `{changed:[...]}` |
| `defs_uses(file, line, col, toolchain="auto")` | Definition + usages of the symbol at a position. | `{def:{file,line,col}\|null, uses:[{file,line,col}]}` |

All results are returned as a single compact `text` content block (JSON when
structured). Whole NIF files are never dumped.

## Manual fallbacks

If a tool degrades (returns `{error, hint}`), the same work can be reproduced by
hand:

- **Nim diagnostics:** `nim check --hints:off --colors:off FILE`
- **Nimony diagnostics:** `nimony c FILE` (ignore `nifmake:` / `FAILURE:` /
  `niflink` lines; trust `Error:` lines, not the exit code).
- **Nim def/use/outline (`nimsuggest`, interactive, Nim-only):**
  ```
  nimsuggest --stdin FILE
  def FILE:LINE:COL
  use FILE:LINE:COL
  outline FILE
  ```
  Results are tab-separated; fields 5/6/7 are file/line/col. `nimsuggest` can be
  slow or flaky, so the server uses a short timeout and degrades to the regex
  outline / an `{error, hint}` result rather than hanging.
- **Nimony def/use (`nimsem idetools`, best-effort):** operates on the `.s.nif`
  in `nimcache`, and the tracked filename must match the **basename** stored in
  that NIF (e.g. `good.nim`, not the absolute path):
  ```
  nimony c FILE                     # produces nimcache/<hash>.s.nif
  nimsem --def:good.nim,LINE,COL   idetools nimcache/<hash>.s.nif
  nimsem --usages:good.nim,LINE,COL idetools nimcache/<hash>.s.nif
  ```
  The server auto-compiles when the `.s.nif` is missing and picks the artifact
  whose `stmts` header names the source basename.

Notes: columns are 1-based on input (editor convention); NIF line numbers from
`nif_outline`/`nif_query` are positions within the NIF stream (best-effort), not
original source lines.

## Test

```
python3 mcp/test_server.py
```

Starts the server as a subprocess and asserts: `initialize`/`tools/list`,
`compile` on a bad Nim **and** a bad Nimony file (diagnostics parse; noise
stripped), plus `nif_outline`/`nif_query`/`nif_diff` against a freshly generated
`nimcache/*.nif`.
