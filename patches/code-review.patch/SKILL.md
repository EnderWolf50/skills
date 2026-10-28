---
name: code-review.patch
description: "Patch for code-review: run both axes in the read-only `CodeReviewer` agent; report in the user's language."
disable-model-invocation: true
user-invocable: false
---

When running `code-review`:

- **Agents.** Step 4 spawns both sub-agents with `subagent_type: CodeReviewer`, falling back to `general-purpose` when that type is not listed. Done: both reviews ran in `CodeReviewer`, or the report names the fallback.
- **The user's language** is the one your instructions tell you to reply in (else the one they write in). Each brief names it ("Write the report in 繁體中文"), and step 5 presents both reports in it, translating rather than quoting verbatim. Code, technical terms, the two headings and quoted hunks and spec lines stay as they are. Done: every other sentence is in the user's language.
