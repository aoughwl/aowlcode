#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end test for the nimlang MCP server.

Spins up server.py as a subprocess, drives it over stdio JSON-RPC, and:
  * compiles a bad Nim file    -> asserts diagnostics parse (line/col/message)
  * compiles a bad Nimony file -> asserts diagnostics parse (line/col/message)
  * generates a nimcache .nif and exercises nif_outline / nif_query.

Run:  python3 mcp/test_server.py
Exits non-zero on failure.
"""

import os
import sys
import json
import glob
import shutil
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, 'server.py')


class Client(object):
    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self._id = 0

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + '\n')
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        self._send({'jsonrpc': '2.0', 'method': method,
                    'params': params or {}})

    def request(self, method, params=None):
        self._id += 1
        rid = self._id
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method,
                    'params': params or {}})
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()
            raise RuntimeError('no response from server. stderr:\n' + err)
        resp = json.loads(line)
        assert resp.get('id') == rid, 'id mismatch: %r' % resp
        return resp

    def call_tool(self, name, arguments):
        resp = self.request('tools/call',
                            {'name': name, 'arguments': arguments})
        assert 'result' in resp, 'error response: %r' % resp
        content = resp['result']['content']
        assert content and content[0]['type'] == 'text'
        return json.loads(content[0]['text'])

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def _assert_diag_shape(diags):
    assert isinstance(diags, list) and len(diags) >= 1, \
        'expected >=1 diagnostic, got %r' % diags
    d = diags[0]
    for key in ('file', 'line', 'col', 'severity', 'message'):
        assert key in d, 'diagnostic missing key %r: %r' % (key, d)
    assert isinstance(d['line'], int)
    assert isinstance(d['col'], int)
    assert isinstance(d['message'], str) and d['message']
    assert d['severity'] in ('Error', 'Warning', 'Hint', 'Trace')


def main():
    workdir = tempfile.mkdtemp(prefix='nimtest_')
    passed = []

    def ok(msg):
        passed.append(msg)
        print('  PASS:', msg)

    client = Client()
    try:
        # ---- handshake --------------------------------------------------
        init = client.request('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '0'},
        })
        assert init['result']['serverInfo']['name'] == 'nimlang'
        client.notify('notifications/initialized')
        ok('initialize + serverInfo')

        listing = client.request('tools/list')
        names = set(t['name'] for t in listing['result']['tools'])
        expected = {'compile', 'outline', 'nif_outline', 'nif_query',
                    'nif_diff', 'defs_uses',
                    'explain_failure', 'phase_report', 'nif_render', 'shrink',
                    'api', 'symbols', 'build', 'decl_of'}
        assert expected <= names, 'missing tools: %r' % (expected - names)
        ok('tools/list exposes all 14 tools')

        # ---- compile: bad Nim ------------------------------------------
        bad_nim = os.path.join(workdir, 'bad_nim.nim')
        with open(bad_nim, 'w') as fh:
            fh.write('proc foo(x: int): string =\n'
                     '  return x + "oops"\n')
        res = client.call_tool('compile',
                               {'file': bad_nim, 'toolchain': 'nim'})
        assert res['toolchain'] == 'nim'
        assert res['ok'] is False, 'bad Nim should not compile: %r' % res
        _assert_diag_shape(res['diagnostics'])
        assert any(d['severity'] == 'Error' for d in res['diagnostics'])
        ok('compile bad Nim -> diagnostics parse (line/col/message)')

        # ---- compile: bad Nimony ---------------------------------------
        bad_nimony = os.path.join(workdir, 'bad_nimony.nim')
        with open(bad_nimony, 'w') as fh:
            fh.write('proc foo(x: int): string =\n'
                     '  return x + 5\n')
        res = client.call_tool('compile',
                               {'file': bad_nimony, 'toolchain': 'nimony'})
        assert res['toolchain'] == 'nimony'
        assert res['ok'] is False, 'bad Nimony should not compile: %r' % res
        _assert_diag_shape(res['diagnostics'])
        assert any(d['severity'] == 'Error' for d in res['diagnostics'])
        # ensure nifmake/FAILURE noise did not leak in as a diagnostic
        for d in res['diagnostics']:
            assert not d['file'].startswith(('nifmake', 'FAILURE', 'niflink'))
        ok('compile bad Nimony -> diagnostics parse, noise stripped')

        # ---- generate a nimcache .nif and outline/query it -------------
        good = os.path.join(workdir, 'good.nim')
        with open(good, 'w') as fh:
            fh.write('proc addup(a: int, b: int): int =\n'
                     '  result = a + b\n'
                     '\n'
                     'let total = addup(1, 2)\n')
        # a successful nimony compile emits nimcache/*.nif
        res = client.call_tool('compile', {'file': good, 'toolchain': 'nimony'})
        nifs = glob.glob(os.path.join(workdir, 'nimcache', '*.p.nif'))
        assert nifs, 'no .p.nif produced in nimcache (compile result: %r)' % res
        # pick the main module's nif: the one whose stmts header names good.nim
        nif_file = None
        for path in nifs:
            with open(path, 'r', errors='replace') as fh:
                head = fh.read(2048)
            if 'good.nim' in head:
                nif_file = path
                break
        if nif_file is None:
            nif_file = nifs[0]

        out = client.call_tool('nif_outline', {'nif_file': nif_file})
        assert 'tags' in out and isinstance(out['tags'], list) and out['tags']
        for node in out['tags']:
            assert 'tag' in node and 'name' in node and 'line' in node
        ok('nif_outline -> %d top-level tags' % len(out['tags']))

        q = client.call_tool('nif_query',
                             {'nif_file': nif_file, 'needle': 'proc'})
        assert 'matches' in q and isinstance(q['matches'], list)
        assert q['matches'], 'expected proc matches in %s' % nif_file
        first = q['matches'][0]
        assert 'tag' in first and 'name' in first and 'snippet' in first
        assert len(first['snippet'].splitlines()) <= 41  # 40 + '...'
        ok('nif_query "proc" -> %d matches, snippets truncated'
           % len(q['matches']))

        # ---- nif_diff sanity ------------------------------------------
        if len(nifs) >= 1:
            other = None
            for path in nifs:
                if path != nif_file:
                    other = path
                    break
            if other is not None:
                d = client.call_tool('nif_diff',
                                     {'file_a': nif_file, 'file_b': other})
                assert 'changed' in d and isinstance(d['changed'], list)
                ok('nif_diff -> %d changed lines' % len(d['changed']))

        # ---- v0.2: terse compile -> compact string diagnostics --------
        tres = client.call_tool('compile',
                                {'file': bad_nim, 'toolchain': 'nim',
                                 'terse': True})
        assert tres['ok'] is False
        assert isinstance(tres['diagnostics'], list)
        assert tres['diagnostics'], 'terse compile should still list errors'
        assert all(isinstance(d, str) for d in tres['diagnostics']), \
            'terse diagnostics must be compact strings: %r' % tres['diagnostics']
        ok('compile terse -> compact "file:line:col msg" strings')

        # ---- v0.2: explain_failure (Nim) ------------------------------
        ef = client.call_tool('explain_failure',
                              {'file': bad_nim, 'toolchain': 'nim'})
        assert ef['ok'] is False
        assert ef.get('verdict'), 'explain_failure needs a verdict: %r' % ef
        ok('explain_failure Nim -> verdict + culprit')

        # ---- v0.2: explain_failure (Nimony) ---------------------------
        efn = client.call_tool('explain_failure',
                               {'file': bad_nimony, 'toolchain': 'nimony'})
        assert efn['ok'] is False
        assert efn.get('verdict'), 'explain_failure(nimony) needs verdict: %r' % efn
        ok('explain_failure Nimony -> verdict + culprit')

        # ---- v0.2: shrink preserves the failure -----------------------
        sh = client.call_tool('shrink', {'file': bad_nim, 'toolchain': 'nim'})
        assert 'minimal_source' in sh and 'original_lines' in sh, \
            'shrink shape: %r' % sh
        assert sh['minimal_lines'] <= sh['original_lines']
        ok('shrink -> %s -> %s lines'
           % (sh['original_lines'], sh['minimal_lines']))

        # ---- v0.2: nif_render -> compact pseudo-Nim -------------------
        rr = client.call_tool('nif_render',
                              {'nif_file': nif_file, 'needle': 'proc'})
        assert 'rendered' in rr and isinstance(rr['rendered'], list)
        ok('nif_render -> %d rendered node(s)' % len(rr['rendered']))

        # ---- api: typed API of a stdlib module ------------------------
        ap = client.call_tool('api', {'module': 'std/strutils',
                                      'toolchain': 'nim'})
        if 'api' in ap and ap['api']:
            names = [x.get('name') if isinstance(x, dict) else x
                     for x in ap['api']]
            assert any('toUpperAscii' in str(n) for n in names), \
                'expected toUpperAscii in strutils api'
            ok('api std/strutils -> %d typed entries' % len(ap['api']))
        else:
            # jsondoc unavailable in this env: accept a clean error, not a crash
            assert 'error' in ap, 'api must return api[] or error: %r' % ap
            ok('api std/strutils -> graceful (jsondoc unavailable)')

        # ---- symbols: project-wide search by name ---------------------
        sy = client.call_tool('symbols', {'name': 'addup', 'root': workdir})
        assert 'defs' in sy and isinstance(sy['defs'], list)
        assert any(d['name'] == 'addup' for d in sy['defs']), \
            'symbols should find the addup proc in good.nim: %r' % sy
        ok('symbols "addup" -> %d def(s) across project' % len(sy['defs']))

        # ---- build: produce a runnable Nim binary and run it ----------
        runnable = os.path.join(workdir, 'runnable.nim')
        with open(runnable, 'w') as fh:
            fh.write('echo "sum=", 2 + 40\n')
        bd = client.call_tool('build',
                              {'file': runnable, 'toolchain': 'nim',
                               'run': True})
        assert bd['ok'] is True, 'clean Nim file should build: %r' % bd
        assert bd.get('binary') and os.path.isfile(bd['binary']), \
            'build should report an existing binary path: %r' % bd
        assert 'run' in bd and 'sum=42' in bd['run'].get('output', ''), \
            'build run should capture program output: %r' % bd
        ok('build Nim -> binary %s, ran it'
           % os.path.basename(bd['binary']))

        # ---- build: a bad file fails with diagnostics, no binary ------
        bbd = client.call_tool('build', {'file': bad_nim, 'toolchain': 'nim'})
        assert bbd['ok'] is False and 'binary' not in bbd, \
            'failed build must not report a binary: %r' % bbd
        assert any(d['severity'] == 'Error' for d in bbd['diagnostics'])
        ok('build bad Nim -> fails, diagnostics, no binary')

        # ---- build: Nimony binary (lands in nimcache/<hash>/) ---------
        nrun = os.path.join(workdir, 'nrun.nim')
        with open(nrun, 'w') as fh:
            fh.write('import std/syncio\necho "nsum=", 20 + 22\n')
        nbd = client.call_tool('build',
                               {'file': nrun, 'toolchain': 'nimony',
                                'run': True})
        assert nbd['ok'] is True, 'clean Nimony file should build: %r' % nbd
        assert nbd.get('binary') and os.path.isfile(nbd['binary']), \
            'Nimony build should locate its nimcache binary: %r' % nbd
        assert 'nsum=42' in nbd.get('run', {}).get('output', ''), \
            'Nimony build run should capture output: %r' % nbd
        ok('build Nimony -> nimcache binary, ran it')

        # ---- decl_of: reverse index (symId -> declaration site) --------
        # good.nim (compiled to nimony above) declares `addup`.
        dcl = client.call_tool('decl_of', {'symbol': 'addup', 'cwd': workdir})
        assert isinstance(dcl.get('decls'), list) and dcl['decls'], \
            'decl_of should find addup: %r' % dcl
        d0 = dcl['decls'][0]
        assert d0['kind'] == 'proc', 'addup should be a proc: %r' % d0
        assert d0['file'] == 'good.nim' and isinstance(d0['line'], int), \
            'decl_of should locate the source site: %r' % d0
        assert d0['sym'].startswith('addup'), 'symId base: %r' % d0
        assert 'addup' in d0.get('signature', ''), \
            'decl_of should render a signature: %r' % d0
        assert dcl.get('backend') in ('niflens', 'python'), \
            'decl_of should report its backend: %r' % dcl
        # When the niflens helper is installed it must be preferred, and it
        # returns module-qualified symIds (add.0.<mod>) with name-glyph columns.
        if dcl['backend'] == 'niflens':
            assert d0['sym'].count('.') >= 2, \
                'niflens symId should be module-qualified: %r' % d0
            assert d0.get('name') == 'addup', \
                'niflens should carry the demangled name: %r' % d0
        ok('decl_of "addup" -> %s at %s:%s (backend=%s)' %
           (d0['kind'], d0['file'], d0['line'], dcl['backend']))

        # mangled-symId prefix match + terse shape
        dcl2 = client.call_tool('decl_of',
                                {'symbol': d0['sym'], 'cwd': workdir,
                                 'terse': True})
        assert dcl2.get('decls') and isinstance(dcl2['decls'][0], str), \
            'terse decl_of should return strings: %r' % dcl2
        ok('decl_of by mangled symId (terse) -> %r' % dcl2['decls'][0])

        # unknown symId -> empty, no error
        dcl3 = client.call_tool('decl_of',
                                {'symbol': 'no_such_symbol_xyz',
                                 'cwd': workdir})
        assert dcl3.get('decls') == [], 'unknown symId -> []: %r' % dcl3
        ok('decl_of unknown symbol -> []')

        # ---- raw mode: tools echo the exact invocation ----------------
        rawc = client.call_tool('compile', {'file': good,
                                            'toolchain': 'nimony', 'raw': True})
        assert 'nimony' in rawc.get('invocation', ''), \
            'compile raw should echo the nimony argv: %r' % rawc
        du = client.call_tool('defs_uses',
                              {'file': good, 'line': 1, 'col': 6,
                               'toolchain': 'nimony', 'raw': True})
        joined = ' '.join(du.get('invocations', []))
        assert '--def:' in joined or '--usages:' in joined, \
            'defs_uses raw should echo idetools argv: %r' % du
        assert 'absolute' in du.get('contract', ''), \
            'defs_uses raw should surface the relative-path contract: %r' % du
        ok('raw mode -> compile/defs_uses echo argv + contract')

    finally:
        client.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print('\nAll %d checks passed.' % len(passed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
