---
name: code-review.patch
description: "Patch for code-review: run both axes in the read-only code-reviewer agent; report in the user's language; record a head that leaves nothing to fix."
disable-model-invocation: true
user-invocable: false
---

When running `code-review`:

- **Agents.** Step 4 spawns the Standards and Spec sub-agents with `subagent_type: code-reviewer`, falling back to `general-purpose` when that type is not listed. The agent is read-only by its tool list, so the prompts carry only the diff, the sources and the brief. Done: both reviews ran in `code-reviewer`, or the report says which fallback was used.
- **The user's language** is the language your instructions tell you to reply to the user in (else the one they write in). Each sub-agent brief names it, for example "Write the report in 繁體中文", since a sub-agent cannot see this session. This overrides step 5's "verbatim": both reports are presented in the user's language, a finding written in another one translated. Code, identifiers, file paths, technical terms (smell names included), the `## Standards` and `## Spec` headings, and quoted hunks and spec lines stay as they are. Done: every sentence outside those kept items is in the user's language.
- **Record.** After step 5, record the reviewed head only when the review leaves nothing to fix: neither axis has a finding that calls for a change, or the user waived each one that does. Append the head's SHA, the date and `code-review` to `reviewed-heads` in the repository's git common dir, which is shared by every worktree:

  ```bash
  echo "$(git -C <worktree> rev-parse HEAD) $(date +%F) code-review" >> "$(git -C <worktree> rev-parse --path-format=absolute --git-common-dir)/reviewed-heads"
  ```

  In PowerShell: `Add-Content "$(git -C <worktree> rev-parse --path-format=absolute --git-common-dir)/reviewed-heads" "$(git -C <worktree> rev-parse HEAD) $(Get-Date -Format yyyy-MM-dd) code-review"`. The `guards` plugin's merge rule lets a pull request merge when its head is on this list. A fix commit makes a new head, which needs its own review before it is recorded. Done: the head is recorded, or the report says which findings still stand, so nothing was recorded.
