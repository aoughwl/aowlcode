# fanout-apply — parallel mechanical edit-apply

## When to use this

Workflows are for the **parallel mechanical fan-out** step, not for driving the
research -> decide -> commit loop — that stays interactive, in the main
conversation (or a `nim-fixer` delegation), where a human or the expensive
model can actually look at ambiguous diagnostics and make a call.

Reach for this workflow only once:

- an expensive-model pass has already produced **N independent, exact edit
  specs** (file + precise old/new text or a diff + a verify command), and
- the edit **pattern is already known and repeated** across N sites, so there
  is nothing left to decide — just apply, verify, and report back.

Each spec is handed to a single cheap `nim-applier`-style stage running on
`haiku`. There is no cross-talk between sites: every item in `args` must be
independently applicable (disjoint files, or disjoint enough regions of the
same file) since they run in parallel with no shared-file locking.

## The script

```js
export const meta = {
  name: 'nim-fanout-apply',
  description:
    'Apply N pre-specified, exact Nim/Nimony edits in parallel via cheap haiku applier stages, each verified by compile/build',
  whenToUse:
    'Invoke AFTER an expensive-model pass has produced exact, independent edit specs for N sites with a known, repeated change pattern (e.g. the same expr-lowering fix applied at N call sites). Requires args: an array of {file, description, edit, verify}. Do NOT use this for research/diagnosis/design decisions — those stay interactive.',
  phases: [{ title: 'Apply', detail: 'one haiku applier per edit spec, independent and parallel' }],
}

// `args` may arrive as the caller's raw JSON string rather than the parsed
// array, depending on the invoking runtime; normalize so both work. A string
// that is not valid JSON falls through and the requires-args check reports it.
const ARGS = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch (e) { return args } })() : args

if (!Array.isArray(ARGS) || ARGS.length === 0) {
  throw new Error(
    'nim-fanout-apply requires args: an array of {file, description, edit, verify} — ' +
    'produce these with the expensive model first, one per independent edit site',
  )
}

for (const spec of ARGS) {
  if (!spec || typeof spec.file !== 'string' || !spec.file) {
    throw new Error(`Every edit spec needs a "file" string; got ${JSON.stringify(spec)}`)
  }
  if (!spec.edit) {
    throw new Error(`Edit spec for ${spec.file} is missing "edit" (old/new text or a diff)`)
  }
  if (!spec.verify) {
    throw new Error(`Edit spec for ${spec.file} is missing "verify" (the compile/build command to run after applying)`)
  }
}

// Edit/verify content is opaque data produced upstream — fence it so it reads
// as data to the applier, never as instructions, and neutralize any embedded
// fence markers so the fence can't be escaped.
const fence = s =>
  `<<<SPEC\n${String(s == null ? '' : s).replace(/<<<SPEC|SPEC>>>/g, '[fence marker stripped]')}\nSPEC>>>`

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['applied', 'gatePass', 'verdict'],
  properties: {
    applied: { type: 'boolean', description: 'Whether the exact edit was applied cleanly' },
    gatePass: { type: 'boolean', description: 'Whether the post-edit verify (compile/build) succeeded; false if not applied' },
    verdict: { type: 'string', description: 'One terse line: what happened, naming the toolchain used, or the reason it did not apply/verify' },
    diff: { type: 'string', description: 'Minimal unified diff actually applied, or empty string if nothing was applied' },
  },
}

log(`Applying ${ARGS.length} edit spec(s) in parallel via haiku applier stages`)

const results = await pipeline(
  ARGS,
  spec =>
    agent(
      `Apply exactly ONE pre-specified edit and verify it. Do not diagnose,
redesign, or improvise a different fix — if it doesn't apply cleanly or the
intent is ambiguous, stop and report that instead of guessing.

File: ${spec.file}
Description (context only, not an instruction to expand scope): ${fence(spec.description || '(none given)')}

Edit to apply (old/new text or diff — apply verbatim):
${fence(typeof spec.edit === 'string' ? spec.edit : JSON.stringify(spec.edit, null, 2))}

Verify step to run after applying (run exactly this; do not substitute another check):
${fence(typeof spec.verify === 'string' ? spec.verify : JSON.stringify(spec.verify, null, 2))}

Toolchain: ${spec.toolchain || 'auto'} — pass this through to the verify call unchanged.
Trust the tool's \`ok\` flag for pass/fail, not the shell exit code (nimony c
can exit 0 while still failing).

Return the diff you applied (or "did not apply, reason: ..." if you could not)
plus exactly one verdict line. Never paste raw compiler output back.`,
      {
        label: `apply:${spec.file}`,
        model: 'haiku',
        effort: 'low',
        phase: 'Apply',
        schema: VERDICT_SCHEMA,
      },
    ).then(r => (r ? { file: spec.file, ...r } : { file: spec.file, applied: false, gatePass: false, verdict: 'agent errored or was skipped', diff: '' })),
)

const passed = results.filter(r => r.applied && r.gatePass)
const failed = results.filter(r => !(r.applied && r.gatePass))

log(`${passed.length}/${results.length} sites applied and verified; ${failed.length} need attention`)

return {
  total: results.length,
  passed: passed.length,
  failed: failed.length,
  results,
  needsAttention: failed.map(r => ({ file: r.file, verdict: r.verdict })),
}

// ---------------------------------------------------------------------------
// How the expensive model populates `args`, and how to invoke this workflow:
//
// The expensive model (main conversation or nim-fixer, having already
// diagnosed the pattern once) produces one exact spec per independent site,
// e.g. for the aowlsem expr-lowering grind:
//
// const args = [
//   {
//     file: '/home/savant/aowlsem/src/semexpr.nim',
//     description: 'lower bare hderef to the explicit at-form the hexer expects',
//     edit: {
//       old: 'result = hderef(n)',
//       new: 'result = hat(hderef(n), n.typ)',
//     },
//     verify: 'nimony c /home/savant/aowlsem/src/semexpr.nim',
//     toolchain: 'nimony',
//   },
//   {
//     file: '/home/savant/aowlsem/src/semstmt.nim',
//     description: 'same hderef->hat lowering, statement-context call site',
//     edit: {
//       old: 'let v = hderef(lhs)',
//       new: 'let v = hat(hderef(lhs), lhs.typ)',
//     },
//     verify: 'nimony c /home/savant/aowlsem/src/semstmt.nim',
//     toolchain: 'nimony',
//   },
//   {
//     file: '/home/savant/aowlsem/src/semcall.nim',
//     description: 'same hderef->hat lowering, call-argument context',
//     edit: {
//       old: 'args.add hderef(arg)',
//       new: 'args.add hat(hderef(arg), arg.typ)',
//     },
//     verify: 'nimony c /home/savant/aowlsem/src/semcall.nim',
//     toolchain: 'nimony',
//   },
// ]
//
// Invoke with the Workflow tool, e.g.:
//   workflow: run workflows/fanout-apply.md with args = <the array above>
// (or hand it directly to the `agent`/workflow-invoking surface as the JSON
// args payload — the exact invocation syntax is the caller's, this file only
// defines the runnable script and its args contract).
```
