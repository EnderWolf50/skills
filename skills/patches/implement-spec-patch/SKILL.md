---
name: implement-spec-patch
description: "Patch for implement-spec: subagents stop the background processes they start before reporting."
disable-model-invocation: true
user-invocable: false
---

When running `implement-spec`, every subagent brief (exploration, implementer, merger, the review-fix implementer) carries this rule:

- **Leave no process behind.** Each background process the subagent starts (dev server, browser, test watcher, `tgrep serve`) is stopped by that subagent before it reports, by PID (`kill <pid>`, then confirm it is gone). Its report lists any process it could not stop, with PID and port. Done: nothing the subagent started still runs, or the report names what does.

Before step 9 (cleaning up worktrees), stop every process the reports listed; a worktree a process still holds stays locked and fails to remove.
