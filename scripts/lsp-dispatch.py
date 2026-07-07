#!/usr/bin/env python3
"""Per-project LSP dispatcher for the nim-code plugin.

Claude Code launches one language server per mapped extension, and its only
documented configuration surface is the plugin's own `.lsp.json`. Nim and
Nimony share the `.nim` extension but need different servers, so this launcher
sits behind the single `.lsp.json` entry, detects which toolchain the current
workspace uses, and `exec`s the matching server — passing stdio straight
through (the LSP is Content-Length framed JSON-RPC over stdin/stdout, which an
`exec` preserves untouched). Exactly one server is ever started, so the
"two servers on one extension" hazard never arises.

Toolchain selection mirrors the MCP server's `detect_toolchain`:
  * `NIMLANG_TOOLCHAIN=nim|nimony` forces the choice;
  * otherwise walk up from the workspace cwd — a `nimony.paths`/`nimony.cfg`,
    or a `nim.cfg` mentioning "nimony", selects Nimony; the default is Nim.

Server binaries (override via env):
  * Nimony -> `NIMONY_LSP` or `nimony-lsp` on PATH
             (also sets `NIMONY_EXE` to the `nimony` on PATH if unset).
  * Nim    -> `NIM_LANGSERVER` or `nimlangserver` on PATH.

If the selected server is not installed we exit non-zero with a one-line
reason (Claude Code surfaces it in the `/plugin` Errors tab). We never fall
back to the other language's server — a wrong-language LSP is worse than none;
the MCP tools continue to cover navigation and diagnostics regardless.
"""

import os
import shutil
import sys


def detect_toolchain(start_dir):
    env = os.environ.get('NIMLANG_TOOLCHAIN')
    if env in ('nim', 'nimony'):
        return env

    d = os.path.abspath(start_dir)
    prev = None
    while d and d != prev:
        for marker in ('nimony.paths', 'nimony.cfg'):
            if os.path.isfile(os.path.join(d, marker)):
                return 'nimony'
        ncfg = os.path.join(d, 'nim.cfg')
        if os.path.isfile(ncfg):
            try:
                with open(ncfg, 'r', errors='replace') as fh:
                    if 'nimony' in fh.read().lower():
                        return 'nimony'
            except Exception:
                pass
        prev = d
        d = os.path.dirname(d)
    return 'nim'


def main():
    toolchain = detect_toolchain(os.getcwd())
    env = dict(os.environ)

    if toolchain == 'nimony':
        server = os.environ.get('NIMONY_LSP') or 'nimony-lsp'
        # Help the server find the compiler on machines where the built-in
        # default path does not apply.
        if not env.get('NIMONY_EXE'):
            nimony = shutil.which('nimony')
            if nimony:
                env['NIMONY_EXE'] = nimony
    else:
        server = os.environ.get('NIM_LANGSERVER') or 'nimlangserver'

    exe = server if os.path.isabs(server) else shutil.which(server)
    if not exe:
        sys.stderr.write(
            'nim-code lsp-dispatch: %s server %r not found on PATH '
            '(toolchain=%s). Install it or set %s.\n' % (
                toolchain, server, toolchain,
                'NIMONY_LSP' if toolchain == 'nimony' else 'NIM_LANGSERVER'))
        sys.exit(127)

    # Forward any extra args Claude Code passed through to the real server.
    argv = [exe] + sys.argv[1:]
    try:
        os.execvpe(exe, argv, env)
    except OSError as e:
        sys.stderr.write('nim-code lsp-dispatch: failed to exec %s: %s\n'
                         % (exe, e))
        sys.exit(126)


if __name__ == '__main__':
    main()
