---
name: merge-pr
description: Merge a GitHub pull request or GitLab merge request once its pipeline is green, pinned to the head commit you checked. Use when asked to merge a PR or MR, now or once its pipeline passes, in place of `gh pr merge` or `glab mr merge`.
---

`scripts/merge_pr.py` reads the request, decides from the forge's own state whether it can merge, and merges through the REST API with the head SHA pinned, so the server refuses a commit pushed after the check (409). It talks to `gh` on a GitHub remote and `glab` on any other, from the current checkout; `--repo` and `--forge` point it elsewhere. `uv run` needs no packages. `<skill>` is this skill's folder.

```
uv run <skill>/scripts/merge_pr.py <number> --target <branch> [--sha <full head sha>] [--require-job <name>]...
                                   [--method merge|squash|rebase] [--timeout 60] [--interval 5] [--dry-run]
```

1. **Pin the head.** Pass `--sha` with the full 40-character head whose diff and pipeline you looked at; without it the script pins the head it reads first and prints it. Pass `--target` with the branch the request is meant for: a request aimed at another branch blocks, which catches a swapped number when two requests pair up (a fix and its backport). Done: you know the head and the target.
2. **Name the jobs the pipeline can pass without.** A manual job with `allow_failure: true`, or a GitHub check that is not required, leaves the pipeline green whether it ran or failed. When the repository's docs require one before merging, pass it as `--require-job` (repeatable): it must have run and passed. Done: every job the repository requires but its pipeline does not is on the command line.
3. **Run it.** To merge only if it is ready now, keep the defaults (60 s, enough for the forge to finish computing mergeability). To merge once a running pipeline passes, raise `--timeout` (for example `--timeout 3600 --interval 30`) and run it in the background. `--dry-run` reports readiness and merges nothing. Done: it exited, and its exit code is one of the rows below.

| Exit | Meaning | Next |
| --- | --- | --- |
| 0 | merged (with `--dry-run`: ready) | report the `merged … as <commit>` line and the issue lines |
| 2 | blocked: head moved, other target, pipeline or required job failed or never played, conflict, draft, review or approval missing, already merged or closed | report the reason it printed; waiting will not change it |
| 3 | timed out while still pending | report what it was waiting on; rerun later, or with a longer `--timeout` |
| 4 | the forge refused the merge until the timeout | report the refusal message it printed |
| 1 | error (a failed API call, bad arguments) | report the message |

- **No pipeline.** A repository with no CI configuration (no `.gitlab-ci.yml` or configured CI path on GitLab, no `.github/workflows` on GitHub) merges without one. A repository that has one but shows no pipeline for this head waits, then exits 3: on GitLab that is also how a pipeline you cannot view looks. `--allow-no-pipeline` merges anyway; pass it only when the user confirms this head is meant to run without one.
- **Issues.** After a merge it prints each issue the request closes, with its state. Closing keywords act only on a merge into the default branch, so a request into a release branch says so and leaves its issues open: close them by hand when the user's process wants that.
- **Method.** GitLab takes the merge method from the project: `squash` sends `squash=true`, `rebase` is refused. GitHub takes `merge` (default), `squash` or `rebase`.

The forge's state values it maps (GitLab `detailed_merge_status`, GitHub `mergeStateStatus` and check conclusions) are documented at https://docs.gitlab.com/api/merge_requests/#merge-status and https://docs.github.com/en/graphql/reference/pulls; `uv run <skill>/scripts/test_merge_pr.py` checks the mapping.
