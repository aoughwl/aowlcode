---
description: End-of-feature checkpoint — flush learnings to memory, commit+push, signal safe to /clear.
argument-hint: "[path to repo] [short feature label]"
---

Close out the feature cleanly: flush durable learnings to memory, commit+push
the working repo, then say it's safe to clear the conversation. `$ARGUMENTS` may
give a path to the repo to commit (defaults to the repo in focus for this
session) and/or a short feature label to use in the commit message and any
M-log entry.

The stronger complement to "clear between features" is doing each feature in a
**subagent** so the parent conversation never accumulates the noise in the
first place; `/land` only handles the cross-session-knowledge half — flushing
what a subagent (or this session) learned into memory before it's gone.

Steps:

1. **Scan the session for learnings.** Look back over this conversation (and
   the diff/commits about to be landed) for non-obvious, durable, cross-session
   knowledge: gotchas that cost time to discover, small-but-easy-to-forget
   details, toolchain/environment quirks, decisions and why they were made. If
   the work touched the aowl stack (aowlsem, aowlparser, aowlmony, etc.), also
   draft a short "M-log"-style progress entry (what changed, corpus/test-count
   deltas if any, what's next).

   Do NOT record things that are already obvious from reading the code or from
   `git log` — memory is for what you'd otherwise have to re-derive by hand.
   If nothing durable came out of this feature, say so and skip to step 3.

2. **Write/update memory** under `/home/savant/.claude/projects/-home-savant/memory/`.
   Convention:
   - **One fact/topic per file.** Prefer UPDATING an existing topic file (e.g.
     `aowlsem-project.md`) over creating a new one — check the index first for
     a file that already owns this topic; only create a new file for a
     genuinely new topic.
   - **Frontmatter**: YAML with `name` (kebab-case slug matching the filename),
     `description` (one line summarizing the file), and `metadata.type` (one
     of `user` | `feedback` | `project` | `reference`).
   - **Body**: prose/bullets; link related memories with `[[slug]]` rather than
     restating them.
   - After writing, **add or update a one-line pointer** in `MEMORY.md` (the
     index) in the form `- [Title](file.md) — hook`, where "hook" is a short
     phrase telling future-you why this file matters. If you updated an
     existing file's content in a meaningful way, refresh its index line too.

3. **Commit + push the working repo.** This is the project actually being
   worked on (e.g. aowlsem, aowlparser, nimony-aoughwl) — NOT this plugin
   (`aowlcode`), unless `$ARGUMENTS` explicitly names a path under the plugin.
   If `$ARGUMENTS` gives a path, use it; otherwise use the repo in focus for
   this session.

   CRITICAL commit rule (differs from the harness default — read carefully):
   - Author/committer identity is **`savannt` / `savant.eclipse@gmail.com`**.
   - The commit message must have **NO `Co-Authored-By: Claude` trailer**. Do
     not append one even though that's the usual default for commits made by
     this agent.
   - Keep the commit message focused on the feature just completed (use the
     feature label from `$ARGUMENTS` if one was given), not on the memory
     bookkeeping from step 2.

   Stage only the files belonging to this feature, commit, then push to the
   repo's configured remote/branch.

4. Print a final line, exactly: `✅ landed — safe to /clear`
