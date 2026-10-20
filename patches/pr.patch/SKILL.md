---
name: pr.patch
description: "Patch for pr: closing keywords that close only what the PR finishes, a Verification section, public-repo text, and PR/issue comment templates."
disable-model-invocation: true
user-invocable: false
---

When running `pr`:

- **Body.** Open with the issue line, then the template's sections, then **Verification**:

  ```markdown
  Closes #<n>
  <or: Refs #<n>: <what this PR does>; left for later: <what remains>>

  ## Summary
  ## Evidence
  ## Merge Danger

  ## Verification

  - Tests: `<command>` → `<passed> passed, <failed> failed`
  - Live: <paths run>; not run: <paths>, each with its follow-up issue
  - Acceptance: `<criterion from the issue>` → met / not met
  - Fixtures: real captures, or synthetic (named `*.synthetic.<ext>`)
  ```

  Every number in Verification is copied from command output in this session; drop a line that does not apply. Done: every "verified" in the body points at the command or clip that shows it.
- **Closing keywords** ([GitHub docs](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)). Write a keyword only for an issue the PR finishes.
  - The keywords are `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`, in any case, optionally with a colon: `Fixes #12`, `Closes: #12`, `fixes owner/repo#12`.
  - One keyword per issue: `Fixes #1, fixes #2` (in `Fixes #1, #2` only #1 closes).
  - They fire when the PR merges into the default branch. A stacked PR's base is another branch, so its keywords do nothing until it is retargeted to the default branch.
  - A commit message closes too, once the commit reaches the default branch; treat a squash commit's message the same way. A commit subject says what changed ("handle empty input"), and carries a keyword only when the commit finishes that issue.
  - Any other word links without closing: `Refs #12`, `Part of #12`, `修正 #12`. Use `Refs #n` when the PR covers part of the issue, and name what remains.
- **Check before submitting** (after `gh pr create`, after each body edit, after a retarget):

  ```bash
  gh pr view <n> --json baseRefName,closingIssuesReferences --jq '{base: .baseRefName, closes: [.closingIssuesReferences[].number]}'
  ```

  Done: `closes` lists exactly the issues the body means to close (empty while the base is not the default branch), and `git log --format=%B origin/<default>..HEAD` holds no keyword for an issue the PR leaves open.
- **Public repo** (`gh repo view --json visibility`, or the repo's AGENTS.md says so). Body, comments and commits describe evidence by its content and attach the files with `--attach '<file>#<alt>'` (`gh pr create`, `gh pr comment`, `gh issue comment`); the text names no local path, account name, UID or e-mail. Follow the repo's AGENTS.md where it says more. Done: every image or clip in the text is an uploaded attachment.
- **Comments** on a PR or an issue (live-test evidence, a review-fix reply, a status update) use [COMMENTS.md](COMMENTS.md).
