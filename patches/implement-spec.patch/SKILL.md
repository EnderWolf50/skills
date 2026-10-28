---
name: implement-spec.patch
description: "Patch for implement-spec: run subagents as `Researcher` and `Implementer` agents, and have each stop the background processes it starts."
disable-model-invocation: true
user-invocable: false
---

When running `implement-spec`, spawn each subagent with the agent type below, falling back to `general-purpose` when that type is not listed:

- exploration subagent (step 2): `subagent_type: Researcher`; the brief names the notes directory it writes to.
- implementer subagents (step 4) and review-fix implementer (step 7): `subagent_type: Implementer`.
- merger subagent (step 5): `subagent_type: Implementer` with `effort: low`; it reports back any conflict in logic the tickets cannot resolve.

Done: every subagent ran in its listed type, or the report names each fallback.

Every subagent brief carries this rule: **leave no process behind.** Each background process the subagent starts (dev server, browser, test watcher, `tgrep serve`) is stopped by that subagent before it reports, by PID (`kill <pid>`, then confirm it is gone). Its report lists any process it could not stop, with PID and port. Done: nothing the subagent started still runs, or the report names what does.

Before step 9 (cleaning up worktrees), stop every process the reports listed; a worktree a process still holds stays locked and fails to remove.
