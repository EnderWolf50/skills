---
name: implement-spec.patch
description: "Patch for implement-spec: route subagents to the researcher and implementer agents; they stop the background processes they start before reporting."
disable-model-invocation: true
user-invocable: false
---

When running `implement-spec`, spawn each subagent with its agent type, falling back to `general-purpose` when that type is not listed:

- the exploration subagent (step 2): `subagent_type: researcher`, the brief naming the notes directory it writes to;
- implementer subagents (step 4) and the review-fix implementer (step 7): `subagent_type: implementer`;
- the merger subagent (step 5): `subagent_type: implementer` with `effort: low`. A merge with conflicts in logic it cannot resolve from the tickets is reported back, not guessed.

Every subagent brief (exploration, implementer, merger, the review-fix implementer) carries this rule:

- **Leave no process behind.** Each background process the subagent starts (dev server, browser, test watcher, `tgrep serve`) is stopped by that subagent before it reports, by PID (`kill <pid>`, then confirm it is gone). Its report lists any process it could not stop, with PID and port. Done: nothing the subagent started still runs, or the report names what does.

Before step 9 (cleaning up worktrees), stop every process the reports listed; a worktree a process still holds stays locked and fails to remove.
