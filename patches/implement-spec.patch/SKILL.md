---
name: implement-spec.patch
description: "Patch for implement-spec: run subagents as researcher/implementer agents, and have each stop the background processes it starts."
disable-model-invocation: true
user-invocable: false
---

When running `implement-spec`, spawn each subagent with the agent type below, falling back to `general-purpose` when that type is not listed:

- exploration subagent (step 2): `subagent_type: researcher`; the brief names the notes directory it writes to.
- implementer subagents (step 4) and review-fix implementer (step 7): `subagent_type: implementer`.
- merger subagent (step 5): `subagent_type: implementer` with `effort: low`; it reports back any conflict in logic the tickets cannot resolve.

Done: every subagent ran in its listed type, or the report names each fallback.

Every subagent brief (exploration, implementer, merger, the review-fix implementer) carries this rule:

- **Leave no process behind.** Each background process the subagent starts (dev server, browser, test watcher, `tgrep serve`) is stopped by that subagent before it reports, by PID (`kill <pid>`, then confirm it is gone). Its report lists any process it could not stop, with PID and port. Done: nothing the subagent started still runs, or the report names what does.

Before step 9 (cleaning up worktrees), stop every process the reports listed; a worktree a process still holds stays locked and fails to remove.
