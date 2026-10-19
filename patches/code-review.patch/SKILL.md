---
name: code-review.patch
description: "Patch for code-review: run both axes in the read-only code-reviewer agent; report in the user's language; record a head that leaves nothing to fix."
disable-model-invocation: true
user-invocable: false
---

When running `code-review`:

- **Agents.** Step 4 spawns both sub-agents with `subagent_type: code-reviewer`, falling back to `general-purpose` when that type is not listed. Done: both reviews ran in `code-reviewer`, or the report names the fallback.
- **The user's language** is the one your instructions tell you to reply in (else the one they write in). Each brief names it ("Write the report in 繁體中文"), and step 5 presents both reports in it, translating rather than quoting verbatim. Code, technical terms, the two headings and quoted hunks and spec lines stay as they are. Done: every other sentence is in the user's language.
- **Pin the head.** At step 1, capture `git rev-parse --verify 'HEAD^{commit}'` and `git rev-parse --path-format=absolute --git-common-dir`, and use that SHA instead of `HEAD` in both diff commands. Worktree edits are not covered. Done: both briefs name the same full SHA.
- **Record.** After step 5, when no finding calls for a change (or the user waived each one), append `<sha> <yyyy-mm-dd> code-review` as one line to `reviewed-heads` in the captured git common dir. The `guards` plugin's merge rule checks the PR head against it; a fix commit is a new SHA and needs its own review. Separate shell calls share no variables, so write the captured values in literally. Done: the line is written, or the report names the remaining findings or the write error.
