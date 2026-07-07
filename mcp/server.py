#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nimlang MCP server for the nim-code Claude Code plugin.

Zero-dependency (stdlib only), Python 3.7 compatible. Speaks JSON-RPC 2.0 over
stdio implementing the MCP subset the plugin needs: initialize,
notifications/initialized, tools/list, tools/call.

Supports BOTH Nim and Nimony toolchains (auto-detected per SPEC, overridable).
See mcp/README.md for the tool list and manual fallbacks.
"""

import sys
import os
import re
import json
import glob
import time
import difflib
import subprocess

# --------------------------------------------------------------------------
# Shared diagnostic parsing
# --------------------------------------------------------------------------

# Identical format for Nim and Nimony:  file(line, col) Sev: message
DIAG_RE = re.compile(
    r'^(?P<file>.+?)\((?P<line>\d+),\s*(?P<col>\d+)\)\s+'
    r'(?P<sev>Error|Warning|Hint|Trace):\s*(?P<msg>.*)$'
)

# Nimony build-driver noise that must be stripped from output.
NOISE_PREFIXES = ('nifmake:', 'FAILURE:', 'niflink', 'nifmake ', 'SUCCESS:')

DEFAULT_TIMEOUT = 120


def parse_diagnostics(text):
    """Return a list of {file,line,col,severity,message} from compiler output.

    Skips Nimony's nifmake/FAILURE/niflink noise lines.
    """
    diags = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(NOISE_PREFIXES):
            continue
        m = DIAG_RE.match(line)
        if m is None:
            continue
        diags.append({
            'file': m.group('file'),
            'line': int(m.group('line')),
            'col': int(m.group('col')),
            'severity': m.group('sev'),
            'message': m.group('msg'),
        })
    return diags


# --------------------------------------------------------------------------
# Binary resolution
# --------------------------------------------------------------------------

def _home(*parts):
    return os.path.join(os.path.expanduser('~'), *parts)


def find_bin(name, env_dir, default_dir):
    """Resolve a binary: PATH first, then env_dir, then default_dir.

    Returns the resolved path (absolute if found in a directory) or just the
    bare name so subprocess can still try PATH as a last resort.
    """
    # 1) PATH
    from shutil import which
    hit = which(name)
    if hit:
        return hit
    exe = name
    if os.name == 'nt' and not name.lower().endswith('.exe'):
        exe = name + '.exe'
    # 2) env override dir
    candidates = []
    override = os.environ.get(env_dir)
    if override:
        candidates.append(os.path.join(override, exe))
    # 3) default dir
    candidates.append(os.path.join(default_dir, exe))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return name


def nim_bin(name):
    return find_bin(name, 'NIM_BIN_DIR', _home('Nim', 'bin'))


def nimony_bin(name):
    return find_bin(name, 'NIMONY_BIN_DIR', _home('nimony', 'bin'))


# --------------------------------------------------------------------------
# Toolchain detection
# --------------------------------------------------------------------------

def detect_toolchain(file_path):
    """auto: walk up from file; nimony if a nimony marker is found, else nim.

    Honors NIMLANG_TOOLCHAIN env override.
    """
    env = os.environ.get('NIMLANG_TOOLCHAIN')
    if env in ('nim', 'nimony'):
        return env

    try:
        d = os.path.dirname(os.path.abspath(file_path))
    except Exception:
        return 'nim'

    prev = None
    while d and d != prev:
        # explicit nimony markers
        for marker in ('nimony.paths', 'nimony.cfg'):
            if os.path.isfile(os.path.join(d, marker)):
                return 'nimony'
        # nim.cfg that mentions nimony
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


def resolve_toolchain(file_path, toolchain):
    if toolchain in ('nim', 'nimony'):
        return toolchain
    return detect_toolchain(file_path)


# --------------------------------------------------------------------------
# subprocess helper
# --------------------------------------------------------------------------

def run(cmd, cwd=None, timeout=DEFAULT_TIMEOUT, stdin_data=None):
    """Run a command, return (returncode, combined_output, timed_out)."""
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE if stdin_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
    except OSError as e:
        return (127, 'failed to launch %s: %s' % (cmd[0], e), False)
    try:
        out, _ = proc.communicate(input=stdin_data, timeout=timeout)
        return (proc.returncode, out or '', False)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, _ = proc.communicate(timeout=5)
        except Exception:
            out = ''
        return (proc.returncode if proc.returncode is not None else -1,
                out or '', True)


# --------------------------------------------------------------------------
# Tool: compile
# --------------------------------------------------------------------------

def tool_compile(args):
    file_path = args.get('file')
    if not file_path:
        return {'error': 'missing required arg: file'}
    toolchain = resolve_toolchain(file_path, args.get('toolchain', 'auto'))
    extra = args.get('extra_args') or []
    if not isinstance(extra, list):
        extra = [str(extra)]
    cwd = os.path.dirname(os.path.abspath(file_path)) or None

    if toolchain == 'nimony':
        cmd = [nimony_bin('nimony'), 'c'] + list(extra) + [file_path]
        stage = 'c'
    else:
        cmd = [nim_bin('nim'), 'check', '--hints:off', '--colors:off'] + \
            list(extra) + [file_path]
        stage = 'check'

    rc, out, timed_out = run(cmd, cwd=cwd, timeout=120)
    diags = parse_diagnostics(out)
    has_error = any(d['severity'] == 'Error' for d in diags)

    if toolchain == 'nimony':
        # exit code is unreliable; presence of any Error line == failure
        ok = not has_error
    else:
        ok = (rc == 0) and not has_error

    result = {
        'ok': ok,
        'toolchain': toolchain,
        'stage': stage,
        'diagnostics': diags,
    }
    if timed_out:
        result['ok'] = False
        result['timed_out'] = True
    return result


# --------------------------------------------------------------------------
# Tool: outline
# --------------------------------------------------------------------------

OUTLINE_RE = re.compile(
    r'^\s*(?P<kind>proc|func|method|template|macro|iterator|converter|'
    r'type|const|var|let)\b[\s*]*(?P<name>[A-Za-z_`][\w`]*)'
)


def outline_regex(file_path):
    symbols = []
    try:
        with open(file_path, 'r', errors='replace') as fh:
            for idx, raw in enumerate(fh, start=1):
                m = OUTLINE_RE.match(raw)
                if m is None:
                    continue
                name = m.group('name').strip('`')
                col = raw.index(m.group('name')) + 1
                symbols.append({
                    'name': name,
                    'kind': m.group('kind'),
                    'line': idx,
                    'col': col,
                })
    except (IOError, OSError) as e:
        return None, str(e)
    return symbols, None


def outline_nimsuggest(file_path):
    """Try nimsuggest 'outline'; return list or None on any trouble."""
    cmd = [nim_bin('nimsuggest'), '--stdin', file_path]
    stdin_data = 'outline %s\nquit\n' % file_path
    rc, out, timed_out = run(cmd, timeout=60, stdin_data=stdin_data)
    if timed_out or not out:
        return None
    symbols = []
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) < 7 or parts[0] != 'outline':
            continue
        # outline \t symkind \t qualname \t sig \t file \t line \t col ...
        kind = parts[1]
        name = parts[2]
        try:
            ln = int(parts[5])
            col = int(parts[6])
        except (ValueError, IndexError):
            continue
        if kind.startswith('sk'):
            kind = kind[2:].lower()
        symbols.append({'name': name, 'kind': kind, 'line': ln, 'col': col})
    if not symbols:
        return None
    return symbols


def tool_outline(args):
    file_path = args.get('file')
    if not file_path:
        return {'error': 'missing required arg: file'}
    toolchain = resolve_toolchain(file_path, args.get('toolchain', 'auto'))

    symbols = None
    used_fallback = True
    if toolchain == 'nim':
        symbols = outline_nimsuggest(file_path)
        if symbols is not None:
            used_fallback = False
    if symbols is None:
        symbols, err = outline_regex(file_path)
        if symbols is None:
            return {'error': err or 'could not read file', 'toolchain': toolchain}
    result = {'toolchain': toolchain, 'symbols': symbols}
    if used_fallback:
        result['source'] = 'regex-fallback'
    return result


# --------------------------------------------------------------------------
# Minimal NIF S-expression scanner
# --------------------------------------------------------------------------

def nif_parse_forms(text):
    """Tiny paren-matching scanner over a NIF stream.

    Returns a flat list of forms, each: {start, end, depth, line, tokens}.
    tokens holds the atom/string tokens that are DIRECT children of the form
    (nested lists are their own forms). Handles NIF string literals ("..." with
    backslash escapes) so parens inside strings do not confuse the scanner.
    """
    forms = []
    stack = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if c == '(':
            form = {'start': i, 'end': n, 'depth': len(stack),
                    'line': line, 'tokens': []}
            stack.append(form)
            forms.append(form)
            i += 1
            continue
        if c == ')':
            if stack:
                stack.pop()['end'] = i + 1
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == '"':
                    break
                if text[j] == '\n':
                    line += 1
                j += 1
            tok = text[i:j + 1]
            i = j + 1
        else:
            j = i
            while j < n and (not text[j].isspace()) and text[j] not in '()':
                j += 1
            tok = text[i:j]
            i = j
        if stack:
            stack[-1]['tokens'].append(tok)
    return forms


def _base_tag(tok):
    """Strip NIF line-info suffix (starting at '@') from a tag token."""
    if tok is None:
        return ''
    return tok.split('@', 1)[0]


def _clean_name(tok):
    if tok is None:
        return ''
    name = tok.split('@', 1)[0]
    name = name.lstrip(':')
    return name


def _read_nif(nif_file):
    with open(nif_file, 'r', errors='replace') as fh:
        return fh.read()


def tool_nif_outline(args):
    nif_file = args.get('nif_file')
    if not nif_file:
        return {'error': 'missing required arg: nif_file'}
    if not os.path.isfile(nif_file):
        return {'error': 'no such file: %s' % nif_file}
    try:
        text = _read_nif(nif_file)
    except (IOError, OSError) as e:
        return {'error': str(e)}

    forms = nif_parse_forms(text)
    # Find the top statement container (stmts). Its direct children are the
    # top-level nodes we want.
    stmts = None
    for f in forms:
        if f['tokens'] and _base_tag(f['tokens'][0]) == 'stmts':
            stmts = f
            break
    tags = []
    if stmts is not None:
        child_depth = stmts['depth'] + 1
        lo, hi = stmts['start'], stmts['end']
        for f in forms:
            if f['depth'] != child_depth:
                continue
            if f['start'] < lo or f['end'] > hi:
                continue
            toks = f['tokens']
            if not toks:
                continue
            tag = _base_tag(toks[0])
            name = _clean_name(toks[1]) if len(toks) > 1 else ''
            tags.append({'tag': tag, 'name': name, 'line': f['line']})
    else:
        # No stmts wrapper: list depth-0 forms as a fallback.
        for f in forms:
            if f['depth'] != 0 or not f['tokens']:
                continue
            tag = _base_tag(f['tokens'][0])
            name = _clean_name(f['tokens'][1]) if len(f['tokens']) > 1 else ''
            tags.append({'tag': tag, 'name': name, 'line': f['line']})
    return {'tags': tags}


def _truncate_snippet(text, max_lines=40, max_chars=2000):
    lines = text.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    snippet = '\n'.join(lines)
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars]
        truncated = True
    if truncated:
        snippet = snippet + '\n...'
    return snippet


def tool_nif_query(args):
    nif_file = args.get('nif_file')
    needle = args.get('needle')
    if not nif_file:
        return {'error': 'missing required arg: nif_file'}
    if not needle:
        return {'error': 'missing required arg: needle'}
    if not os.path.isfile(nif_file):
        return {'error': 'no such file: %s' % nif_file}
    try:
        text = _read_nif(nif_file)
    except (IOError, OSError) as e:
        return {'error': str(e)}

    needle_l = needle.lower()
    forms = nif_parse_forms(text)
    matches = []
    seen = set()
    cap = 50
    for f in forms:
        toks = f['tokens']
        if not toks:
            continue
        tag = _base_tag(toks[0])
        name = _clean_name(toks[1]) if len(toks) > 1 else ''
        head = ' '.join(toks[:2]).lower()
        if tag.lower() == needle_l or needle_l in head:
            key = (f['start'], f['end'])
            if key in seen:
                continue
            seen.add(key)
            snippet = _truncate_snippet(text[f['start']:f['end']])
            matches.append({'tag': tag, 'name': name, 'snippet': snippet})
            if len(matches) >= cap:
                break
    return {'matches': matches, 'count': len(matches)}


# --------------------------------------------------------------------------
# Tool: nif_diff
# --------------------------------------------------------------------------

def tool_nif_diff(args):
    a = args.get('file_a')
    b = args.get('file_b')
    if not a or not b:
        return {'error': 'missing required args: file_a, file_b'}
    for p in (a, b):
        if not os.path.isfile(p):
            return {'error': 'no such file: %s' % p}
    try:
        with open(a, 'r', errors='replace') as fh:
            la = fh.read().splitlines()
        with open(b, 'r', errors='replace') as fh:
            lb = fh.read().splitlines()
    except (IOError, OSError) as e:
        return {'error': str(e)}

    diff = difflib.unified_diff(
        la, lb, fromfile=os.path.basename(a), tofile=os.path.basename(b),
        n=1, lineterm='')
    changed = []
    for line in diff:
        # trim the ---/+++ file header lines (keep @@ hunk markers + edits)
        if line.startswith('--- ') or line.startswith('+++ '):
            continue
        changed.append(line)
    return {'changed': changed}


# --------------------------------------------------------------------------
# Tool: defs_uses
# --------------------------------------------------------------------------

def nimsuggest_query(section, file_path, line, col):
    """Run one nimsuggest def/use query. Returns list of {file,line,col}."""
    cmd = [nim_bin('nimsuggest'), '--stdin', file_path]
    stdin_data = '%s %s:%d:%d\nquit\n' % (section, file_path, line, col)
    rc, out, timed_out = run(cmd, timeout=60, stdin_data=stdin_data)
    if timed_out or not out:
        return None
    results = []
    for l in out.splitlines():
        parts = l.split('\t')
        if len(parts) < 7 or parts[0] != section:
            continue
        try:
            ln = int(parts[5])
            cl = int(parts[6])
        except (ValueError, IndexError):
            continue
        results.append({'file': parts[4], 'line': ln, 'col': cl})
    return results


def defs_uses_nim(file_path, line, col):
    defs = nimsuggest_query('def', file_path, line, col)
    uses = nimsuggest_query('use', file_path, line, col)
    if defs is None and uses is None:
        # nimsuggest unavailable/flaky -> degrade
        return {
            'def': None,
            'uses': [],
            'error': 'nimsuggest unavailable or timed out',
            'hint': 'run manually: nimsuggest --stdin %s then '
                    'def/use %s:%d:%d' % (file_path, file_path, line, col),
        }
    def_obj = defs[0] if defs else None
    return {'def': def_obj, 'uses': uses or []}


def _find_s_nif(cwd, basename):
    """Find the .s.nif in cwd/nimcache whose stmts header names basename."""
    ncache = os.path.join(cwd, 'nimcache')
    candidates = sorted(glob.glob(os.path.join(ncache, '*.s.nif')),
                        key=os.path.getmtime, reverse=True)
    header_marker = ',' + basename
    for path in candidates:
        try:
            with open(path, 'r', errors='replace') as fh:
                head = fh.read(4096)
        except (IOError, OSError):
            continue
        # first stmts line looks like: (stmts@,1,good.nim
        if header_marker in head.splitlines()[0] if head else False:
            return path
        for hl in head.splitlines()[:4]:
            if hl.startswith('(stmts') and header_marker in hl:
                return path
    return None


def _nimsem_idetools(mode_flag, nif_file, basename, line, col):
    """mode_flag: '--usages' or '--def'. Returns list of {file,line,col}."""
    track = '%s:%s,%d,%d' % (mode_flag, basename, line, col)
    cmd = [nimony_bin('nimsem'), track, 'idetools', nif_file]
    rc, out, timed_out = run(cmd, timeout=60)
    if timed_out or not out:
        return None
    results = []
    for l in out.splitlines():
        parts = l.split('\t')
        if len(parts) < 3:
            continue
        kind = parts[0].strip()
        if kind not in ('use', 'def'):
            continue
        # kind \t ... \t symname \t ... \t file \t line \t col
        try:
            cl = int(parts[-1])
            ln = int(parts[-2])
            fl = parts[-3]
        except (ValueError, IndexError):
            continue
        results.append({'file': fl, 'line': ln, 'col': cl})
    return results


def defs_uses_nimony(file_path, line, col):
    cwd = os.path.dirname(os.path.abspath(file_path)) or '.'
    basename = os.path.basename(file_path)
    hint = ('build the file first (nimony c %s), then run: nimsem '
            '--usages:%s,%d,%d idetools nimcache/<hash>.s.nif'
            % (file_path, basename, line, col))

    s_nif = _find_s_nif(cwd, basename)
    if s_nif is None:
        # try compiling to produce the artifact
        run([nimony_bin('nimony'), 'c', file_path], cwd=cwd, timeout=120)
        s_nif = _find_s_nif(cwd, basename)
    if s_nif is None:
        return {'def': None, 'uses': [],
                'error': 'no .s.nif artifact found in %s/nimcache' % cwd,
                'hint': hint}

    defs = _nimsem_idetools('--def', s_nif, basename, line, col)
    uses = _nimsem_idetools('--usages', s_nif, basename, line, col)
    if defs is None and uses is None:
        return {'def': None, 'uses': [],
                'error': 'nimsem idetools unavailable or timed out',
                'hint': hint}
    def_obj = defs[0] if defs else None
    return {'def': def_obj, 'uses': uses or [], 'nif': s_nif}


def tool_defs_uses(args):
    file_path = args.get('file')
    if not file_path:
        return {'error': 'missing required arg: file'}
    try:
        line = int(args.get('line'))
        col = int(args.get('col'))
    except (TypeError, ValueError):
        return {'error': 'line and col must be integers'}
    toolchain = resolve_toolchain(file_path, args.get('toolchain', 'auto'))
    if toolchain == 'nimony':
        return defs_uses_nimony(file_path, line, col)
    return defs_uses_nim(file_path, line, col)


# --------------------------------------------------------------------------
# Tool registry / schemas
# --------------------------------------------------------------------------

TOOLCHAIN_ENUM = {'type': 'string', 'enum': ['auto', 'nim', 'nimony'],
                  'default': 'auto',
                  'description': 'Toolchain: auto-detect (default) or force.'}

TOOLS = [
    {
        'name': 'compile',
        'description': 'Type-check/compile a Nim or Nimony file and return '
                       'structured diagnostics (no verbose noise).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'file': {'type': 'string', 'description': 'Path to .nim file.'},
                'toolchain': TOOLCHAIN_ENUM,
                'extra_args': {'type': 'array', 'items': {'type': 'string'},
                               'description': 'Extra compiler args.'},
            },
            'required': ['file'],
        },
        'handler': tool_compile,
    },
    {
        'name': 'outline',
        'description': 'List top-level symbols (procs/types/vars...) of a Nim '
                       'or Nimony source file.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'file': {'type': 'string'},
                'toolchain': TOOLCHAIN_ENUM,
            },
            'required': ['file'],
        },
        'handler': tool_outline,
    },
    {
        'name': 'nif_outline',
        'description': 'Top-level tag/name nodes of a Nimony NIF artifact '
                       '(no bodies). Use instead of reading whole .nif files.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'nif_file': {'type': 'string',
                             'description': 'Path to a .nif file.'},
            },
            'required': ['nif_file'],
        },
        'handler': tool_nif_outline,
    },
    {
        'name': 'nif_query',
        'description': 'Return only the NIF subtrees whose head tag or symbol '
                       'matches a needle (each snippet truncated).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'nif_file': {'type': 'string'},
                'needle': {'type': 'string',
                           'description': 'Tag or symbol substring to find.'},
            },
            'required': ['nif_file', 'needle'],
        },
        'handler': tool_nif_query,
    },
    {
        'name': 'nif_diff',
        'description': 'Compact structural/line diff between two NIF (or text) '
                       'files, collapsing unchanged regions.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'file_a': {'type': 'string'},
                'file_b': {'type': 'string'},
            },
            'required': ['file_a', 'file_b'],
        },
        'handler': tool_nif_diff,
    },
    {
        'name': 'defs_uses',
        'description': 'Definition + usages of the symbol at file:line:col. '
                       'Nim via nimsuggest, Nimony via nimsem idetools.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'file': {'type': 'string'},
                'line': {'type': 'integer'},
                'col': {'type': 'integer'},
                'toolchain': TOOLCHAIN_ENUM,
            },
            'required': ['file', 'line', 'col'],
        },
        'handler': tool_defs_uses,
    },
]

TOOLS_BY_NAME = {}
for _t in TOOLS:
    TOOLS_BY_NAME[_t['name']] = _t


def tools_list_payload():
    out = []
    for t in TOOLS:
        out.append({
            'name': t['name'],
            'description': t['description'],
            'inputSchema': t['inputSchema'],
        })
    return out


# --------------------------------------------------------------------------
# JSON-RPC / MCP plumbing
# --------------------------------------------------------------------------

PROTOCOL_VERSION = '2024-11-05'
SERVER_INFO = {'name': 'nimlang', 'version': '0.1.0'}


def make_response(req_id, result):
    return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def make_error(req_id, code, message):
    return {'jsonrpc': '2.0', 'id': req_id,
            'error': {'code': code, 'message': message}}


def handle_tools_call(params):
    name = params.get('name')
    arguments = params.get('arguments') or {}
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {'content': [{'type': 'text',
                             'text': json.dumps({'error': 'unknown tool: %s'
                                                 % name})}],
                'isError': True}
    try:
        result = tool['handler'](arguments)
    except Exception as e:
        result = {'error': 'tool %s crashed: %s' % (name, e)}
    is_error = isinstance(result, dict) and 'error' in result
    text = json.dumps(result, separators=(',', ':'), ensure_ascii=False)
    payload = {'content': [{'type': 'text', 'text': text}]}
    if is_error:
        payload['isError'] = True
    return payload


def dispatch(msg):
    """Return a response dict, or None for notifications."""
    method = msg.get('method')
    req_id = msg.get('id')
    params = msg.get('params') or {}

    if method == 'initialize':
        return make_response(req_id, {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {'tools': {}},
            'serverInfo': SERVER_INFO,
        })
    if method == 'notifications/initialized' or method == 'initialized':
        return None
    if method == 'ping':
        return make_response(req_id, {})
    if method == 'tools/list':
        return make_response(req_id, {'tools': tools_list_payload()})
    if method == 'tools/call':
        return make_response(req_id, handle_tools_call(params))

    if req_id is None:
        return None  # unknown notification, ignore
    return make_error(req_id, -32601, 'method not found: %s' % method)


def main():
    stdin = sys.stdin
    stdout = sys.stdout
    while True:
        line = stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = make_error(None, -32700, 'parse error')
            stdout.write(json.dumps(resp) + '\n')
            stdout.flush()
            continue
        # Support batch arrays defensively.
        if isinstance(msg, list):
            for sub in msg:
                resp = dispatch(sub)
                if resp is not None:
                    stdout.write(json.dumps(resp) + '\n')
            stdout.flush()
            continue
        resp = dispatch(msg)
        if resp is not None:
            stdout.write(json.dumps(resp) + '\n')
            stdout.flush()


if __name__ == '__main__':
    main()
