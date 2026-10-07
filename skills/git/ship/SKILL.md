---
name: ship
description: Take finished work to a pull request ready for review - commit, push, open the pull request, optionally arm auto-merge, watch the pipeline, report its URL. Use when the user says ship or "push & PR/MR", or asks for auto-merge or pipeline monitoring.
---

Each step ends on its own done-condition; stop and report when one cannot be met. The forge follows `git remote get-url origin`: github.com is GitHub (`gh`), anything else is GitLab (`glab`, where a pull request is a merge request).

1. **Where.** `git rev-parse --show-toplevel` must be a linked worktree (the repo's sibling `.wt/` directory, per its `AGENTS.md`) on a feature branch, never the main checkout or the default branch. Done: branch name printed and it is not the default branch.
2. **Commit** with explicit paths (never `-a`), message per the repo's `AGENTS.md` git workflow. Done: `git status --short` lists nothing you meant to ship.
3. **Push**: `git push -u origin HEAD`. Done: the remote branch exists.
4. **Open** the pull request per the repo's pull/merge request doc (e.g. `docs/agents/merge-request.md`: template, labels, evidence); with no such doc, `gh pr create --fill` / `glab mr create --fill`. Done: its number and URL are known (the create command prints the URL; `gh pr view <n> --json url` / `glab mr view <n>` otherwise).
5. **Auto-merge**, only when the user asked for it: arm it per `references/auto-merge.md`. Otherwise the pull request waits for the user's review.
6. **Watch**: run `bash ~/.agents/skills/ship/scripts/watch-pr.sh <number>` from the repo under Monitor. It prints `<state> pipeline=<status> merge=<status>` when the state or pipeline changes or a conflict appears, and exits on a green or skipped pipeline, `merged`, `closed`, a failed/canceled pipeline, or a conflict with the target branch. On a failure, read the red job (`gh pr checks <n>` / `gh run view <run-id> --log-failed`, or `glab ci view` / `glab ci trace <job-id>`) and report its cause; on a conflict, rebase per `~/.agents/skills/pr-sweep/references/rebase.md`, re-arm auto-merge if it was armed, and watch again. Done: pipeline green, or the failing job's cause or the unresolved conflict reported.
7. **Clean up**, only when the user asked: `git worktree remove <path>` and delete the local branch. A directory locked by a running process (tgrep serve, a dev server) is reported, not force-deleted. Done: worktree and branch gone, or the lock reported.
8. **Report** the pull request URL as a markdown link the user can click to review, with the pipeline result and whether auto-merge is armed. Without auto-merge, merging is the user's call after review.
