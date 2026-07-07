---
name: token-thrift
description: >-
  Read this when working on Nim or Nimony code in this repo and you care about
  token efficiency: how to get compiler diagnostics, phase info, and NIF
  artifacts without flooding the context. Use before running a manual
  compile -> list -> outline -> query sequence, catting a .nif, or grinding a
  verbose fix loop inline.
---

# Token thrift for Nim / Nimony work

Keep the main thread lean. The plugin exists to stop verbose compiler and NIF
output from eating your context. Follow these rules.

## Prefer the recipe tools over manual multi-call sequences

- `explain_failure(file)` — one call gives `ok` + a <=5-line `verdict` +
  diagnostics + `culprit` (the smallest failing NIF node / source slice). Use it
  instead of `compile` -> `outline` -> `nif_query` by hand.
- `phase_report(file)` — one-line-per-phase summary of the Nimony pipeline
  (tag counts + size), no raw NIF. Use it instead of listing and reading each
  `nimcache/*.nif`.

## Enable terse mode

Set env `NIMLANG_AGGRESSIVE=1` (or `/aggressive on`), or pass `terse: true` per
call. Terse collapses diagnostics to `"file:line:col msg"` strings, drops
warnings/hints, and tightens NIF snippet caps.

## Never `cat` / `head` / `tail` a `.nif` file

NIF artifacts are large S-expression streams. Use `nif_outline` (top-level
tags), `nif_query` (matching subtrees only), or `nif_render` (compact
pseudo-Nim, ~10x smaller), or the `/nif` and `/render` commands. Raw reads of big
`.nif` files are blocked by the plugin hooks anyway.

## Offload verbose fix loops to the `nim-fixer` subagent

For "make this compile" / iterate-until-it-builds work, delegate to the
`nim-fixer` subagent (cheap haiku model). It runs the whole
compile -> shrink -> explain -> edit -> recompile loop in its own context and
returns only the final diff + a one-line verdict — the noisy output never
touches the main thread.

## Let the hooks do their job

The plugin hooks already trim `nifmake:` / `FAILURE:` / `niflink` build noise and
transform blocked `.nif` reads into compact outlines. Do not fight them or
re-fetch what they stripped — trust the surfaced diagnostics.
