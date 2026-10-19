---
name: code-review.patch
description: "Patch for code-review: run both axes in the read-only code-reviewer agent; report in the user's language."
disable-model-invocation: true
user-invocable: false
---

When running `code-review`:

- **Agents.** Step 4 spawns the Standards and Spec sub-agents with `subagent_type: code-reviewer`, falling back to `general-purpose` when that type is not listed. The agent is read-only by its tool list, so the prompts carry only the diff, the sources and the brief. Done: both reviews ran in `code-reviewer`, or the report says which fallback was used.
- **The user's language** is the language your instructions tell you to reply to the user in (else the one they write in). Each sub-agent brief names it, for example "Write the report in 繁體中文", since a sub-agent cannot see this session. This overrides step 5's "verbatim": both reports are presented in the user's language, a finding written in another one translated. Code, identifiers, file paths, technical terms (smell names included), the `## Standards` and `## Spec` headings, and quoted hunks and spec lines stay as they are. Done: every sentence outside those kept items is in the user's language.
