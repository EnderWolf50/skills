---
name: diagnosing-bugs.patch
description: "Patch for diagnosing-bugs: check the siblings sharing the root cause's pattern before proposing the fix."
disable-model-invocation: true
user-invocable: false
---

When running `diagnosing-bugs`:

- **Siblings**, between Phase 4 and Phase 5: once the root cause is confirmed, list every sibling that runs the same code path or repeats the same misuse, taking the list from the repo's docs when it documents one. Check each, show a table of sibling × result (affected, clean, n/a with the reason), and scope the fix to every affected row. Done: every listed sibling has a result.
