---
name: diagnosing-bugs.patch
description: "Patch for diagnosing-bugs: check the siblings sharing the root cause's pattern before proposing the fix."
disable-model-invocation: true
user-invocable: false
---

When running `diagnosing-bugs`:

- **Siblings**, between Phase 4 and Phase 5: once the root cause is confirmed, list every sibling that shares its pattern: the other domains, controllers, views or pages that run the same code path or repeat the same misuse. When the repo documents its domain list (a `docs/agents/` file, `AGENTS.md`), take the list from there. Check each sibling, then show a table of sibling × result (affected, clean, n/a with the reason) before proposing the fix, and scope the fix to every affected row. Done: every listed sibling has a result in the table.
