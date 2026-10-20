---
name: pr.patch
description: "Patch for pr: closing keywords that close only the issues the PR finishes, checked against GitHub before submitting."
disable-model-invocation: true
user-invocable: false
---

When running `pr`:

- **Issue line.** The body opens with `Closes #<n>` for each issue the PR finishes, or `Refs #<n>: <what this PR does>; left for later: <what remains>` for one it covers in part. Then the template's sections, plus whatever the repo's AGENTS.md adds.
- **Closing keywords** ([GitHub docs](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)). Write a keyword only for an issue the PR finishes.
  - The keywords are `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`, in any case, optionally with a colon: `Fixes #12`, `Closes: #12`, `fixes owner/repo#12`.
  - One keyword per issue: `Fixes #1, fixes #2` (in `Fixes #1, #2` only #1 closes).
  - They fire when the PR merges into the default branch. A stacked PR's base is another branch, so its keywords do nothing until it is retargeted to the default branch.
  - A commit message closes too, once the commit reaches the default branch; treat a squash commit's message the same way. A commit subject says what changed ("handle empty input"), and carries a keyword only when the commit finishes that issue.
  - Any other word links without closing: `Refs #12`, `Part of #12`, `修正 #12`.
- **Check before submitting** (after `gh pr create`, after each body edit, after a retarget):

  ```bash
  gh pr view <n> --json baseRefName,closingIssuesReferences --jq '{base: .baseRefName, closes: [.closingIssuesReferences[].number]}'
  ```

  Done: `closes` lists exactly the issues the body means to close (empty while the base is not the default branch), and `git log --format=%B origin/<default>..HEAD` holds no keyword for an issue the PR leaves open.
