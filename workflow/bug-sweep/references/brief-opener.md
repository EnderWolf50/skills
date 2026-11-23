# Opener brief

Fill every `{…}` and send the block below to an `Implementer` agent (model sonnet, effort medium), one per verified branch. A backport opener gets the same brief with the backport block in place of step 2.

```markdown
Read and follow {skill}/references/rules.md first; you are the one role that pushes and opens the request. Repository rules on top of it:
{work.rules, one bullet each}

Goal: open a {GitLab merge request | GitHub pull request} for branch `{branch}` in worktree `{worktree}`, fixing issue {issue URL}, and report its URL and head SHA. Read these first: {docs.opener}. Leave the merge to the orchestrator.

1. Claim check: the issue is still assigned to {assignee} and no other open request names it. If not, stop and report.
2. Update: `git fetch origin`, then {`git rebase origin/{default branch}` | `git merge --no-edit origin/{default branch}`}. A conflict is resolved for the target's code and described in the request. When the update brought changes to files the fix touches, rerun the fixer's gates.
3. Pre-push checks, each must pass: {request.pre_push, or "none configured"}.
4. Push: `git push -u origin {branch}`.
5. Open it with the repository's template ({request.template}), title in {request.language} with no Conventional Commit prefix, labels {request.labels}, milestone {issue's | current | none}, draft {request.draft}. The description names the issue as `Closes {issue URL}` and pastes the verification evidence below; write it to a file and pass it by path (`--description-file` / `--body-file`).
6. Read the request back and confirm its source branch, target and head SHA.

Verification evidence from the fixer and the verifier:
{test output, gates run, verifier verdict}

Report, as your final message: request URL, head SHA (full 40 characters), target branch, and anything you could not do.
```

Backport block, in place of step 2:

```markdown
2. Backport: `git fetch origin`, then `git switch -c {backport branch} origin/{release branch}` and `git cherry-pick -x {merged commits, in order}`. A conflict means the release differs there: resolve it for the release's code and say what differed. Read {docs.backport} first; its conditions win over this brief. Target `{release branch}`; the description names the source request's full URL and the cherry-picked commits.
```
