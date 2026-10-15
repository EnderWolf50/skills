---
name: code-review.patch
description: "Patch for code-review: run both axes in the read-only code-reviewer agent."
disable-model-invocation: true
user-invocable: false
---

When running `code-review`, step 4 spawns the Standards and Spec sub-agents with `subagent_type: code-reviewer`, falling back to `general-purpose` when that type is not listed. The agent is read-only by its tool list, so the prompts carry only the diff, the sources and the brief. Done: both reviews ran in `code-reviewer`, or the report says which fallback was used.
