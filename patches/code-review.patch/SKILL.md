---
name: code-review.patch
description: "Patch for code-review: run both axes in the read-only code-reviewer agent; report in the user's language."
disable-model-invocation: true
user-invocable: false
---

When running `code-review`:

- **Agents.** Step 4 spawns the Standards and Spec sub-agents with `subagent_type: code-reviewer`, falling back to `general-purpose` when that type is not listed. The agent is read-only by its tool list, so the prompts carry only the diff, the sources and the brief. Done: both reviews ran in `code-reviewer`, or the report says which fallback was used.
- **Language.** Both sub-agent briefs ask for the report in the language the session replies to the user in, and step 5 presents both reports in that language: a finding written in another language is translated, while code, identifiers, file paths, quoted hunks and quoted spec lines stay as they are. The `## Standards` and `## Spec` headings and the per-axis separation stay. Done: every sentence of the aggregated report is in the user's language.
