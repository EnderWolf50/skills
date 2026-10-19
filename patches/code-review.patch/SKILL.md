---
name: code-review.patch
description: "Patch for code-review: run both axes in the read-only code-reviewer agent; report in the user's language; record a head that leaves nothing to fix."
disable-model-invocation: true
user-invocable: false
---

When running `code-review`:

- **Agents.** Step 4 spawns the Standards and Spec sub-agents with `subagent_type: code-reviewer`, falling back to `general-purpose` when that type is not listed. The agent is read-only by its tool list, so the prompts carry only the diff, the sources and the brief. Done: both reviews ran in `code-reviewer`, or the report says which fallback was used.
- **The user's language** is the language your instructions tell you to reply to the user in (else the one they write in). Each sub-agent brief names it, for example "Write the report in 繁體中文", since a sub-agent cannot see this session. This overrides step 5's "verbatim": both reports are presented in the user's language, a finding written in another one translated. Code, identifiers, file paths, technical terms (smell names included), the `## Standards` and `## Spec` headings, and quoted hunks and spec lines stay as they are. Done: every sentence outside those kept items is in the user's language.
- **Pin the reviewed head.** At step 1, capture the full commit SHA and the repository's git common dir. Use that SHA in both axes' diff commands instead of `HEAD`, and inspect the committed tree at that SHA. Worktree edits are not covered. In Bash:

  ```bash
  review_head=$(git -C "<worktree>" rev-parse --verify 'HEAD^{commit}') &&
    review_git_dir=$(git -C "<worktree>" rev-parse --path-format=absolute --git-common-dir) || exit 1
  ```

  In PowerShell:

  ```powershell
  $reviewHead = git -C "<worktree>" rev-parse --verify 'HEAD^{commit}'
  if ($LASTEXITCODE -ne 0) { throw 'Could not pin the reviewed head' }
  $reviewGitDir = git -C "<worktree>" rev-parse --path-format=absolute --git-common-dir
  if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the review record directory' }
  ```

  Done: both briefs name the same full SHA and its resolved record directory.
- **Record.** After step 5, record the pinned SHA only when neither axis has a finding that calls for a change, or the user waived each one that does. Append the SHA, date and `code-review` to `reviewed-heads` in the captured git common dir, shared by every worktree and never committed. In Bash:

  ```bash
  printf '%s %s code-review\n' "$review_head" "$(date +%F)" >> "$review_git_dir/reviewed-heads"
  ```

  In PowerShell:

  ```powershell
  Add-Content -LiteralPath "$reviewGitDir/reviewed-heads" -Value "$reviewHead $(Get-Date -Format yyyy-MM-dd) code-review" -ErrorAction Stop
  ```

  Use the captured values literally when setup and recording run in separate shell calls. The `guards` plugin's merge rule checks the PR head against this list. A fix commit makes a new SHA, which needs its own review. Done: the recorded SHA matches both briefs, or the report names the remaining findings or write failure and no successful record is claimed.
