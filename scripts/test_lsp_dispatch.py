#!/usr/bin/env python3
"""Selection tests for lsp-dispatch.py. No compiler needed: a shim server
(`/bin/echo`) stands in for the real LSP so we can observe which one the
dispatcher chose and that it exits cleanly when the server is missing.

Run: python3 scripts/test_lsp_dispatch.py
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DISPATCH = os.path.join(HERE, 'lsp-dispatch.py')

fails = []


def run(cwd, env_extra, args=()):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, DISPATCH, *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=15)


def check(name, cond, detail=''):
    if cond:
        print('  PASS: ' + name)
    else:
        print('  FAIL: %s %s' % (name, detail))
        fails.append(name)


def main():
    with tempfile.TemporaryDirectory() as root:
        nimdir = os.path.join(root, 'nim'); os.makedirs(nimdir)
        nimonydir = os.path.join(root, 'nimony'); os.makedirs(nimonydir)
        open(os.path.join(nimonydir, 'nimony.paths'), 'w').close()

        # Nim project (no marker) -> nimlangserver shim (echo prints its arg).
        r = run(nimdir, {'NIM_LANGSERVER': '/bin/echo'}, ['NIM_PICKED'])
        check('nim project selects NIM_LANGSERVER',
              r.returncode == 0 and 'NIM_PICKED' in r.stdout, repr(r.stdout))

        # Nimony marker -> nimony-lsp shim.
        r = run(nimonydir, {'NIMONY_LSP': '/bin/echo'}, ['NIMONY_PICKED'])
        check('nimony.paths marker selects NIMONY_LSP',
              r.returncode == 0 and 'NIMONY_PICKED' in r.stdout, repr(r.stdout))

        # Env override forces nimony even without a marker.
        r = run(nimdir, {'NIMLANG_TOOLCHAIN': 'nimony',
                         'NIMONY_LSP': '/bin/echo'}, ['FORCED'])
        check('NIMLANG_TOOLCHAIN=nimony overrides detection',
              r.returncode == 0 and 'FORCED' in r.stdout, repr(r.stdout))

        # Env override forces nim even under a nimony marker.
        r = run(nimonydir, {'NIMLANG_TOOLCHAIN': 'nim',
                            'NIM_LANGSERVER': '/bin/echo'}, ['FORCED_NIM'])
        check('NIMLANG_TOOLCHAIN=nim overrides marker',
              r.returncode == 0 and 'FORCED_NIM' in r.stdout, repr(r.stdout))

        # Missing server -> non-zero exit, reason on stderr, no wrong-lang fallback.
        r = run(nimonydir, {'NIMONY_LSP': 'nimony-lsp-does-not-exist-xyz'})
        check('missing server exits non-zero with reason',
              r.returncode == 127 and 'not found' in r.stderr, repr(r.stderr))

    print()
    if fails:
        print('FAILED: %d check(s): %s' % (len(fails), ', '.join(fails)))
        sys.exit(1)
    print('All %d dispatcher checks passed.' % 5)


if __name__ == '__main__':
    main()
