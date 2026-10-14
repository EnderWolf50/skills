# Arming auto-merge

Done: auto-merge armed, or `merged` after the user chose an immediate merge.

- GitHub: `gh pr merge <n> --auto --delete-branch` with the repo's merge method (`--squash`, `--merge` or `--rebase`). It needs "Allow auto-merge" in the repo settings: `gh api repos/{owner}/{repo} --jq .allow_auto_merge` (`gh repo view` has no such field). When it is `false`, the user's ask for auto-merge means: watch to green, then merge per `~/.agents/skills/ship/references/land.md`. With no required checks GitHub merges at once, so ask the user first when `gh pr checks <n>` lists none.
- GitLab: `glab mr merge --auto-merge` merges *immediately* while the pipeline is still `pending`; arm it through the API, which accepts a pending pipeline:
  ```sh
  glab api --method PUT "projects/:id/merge_requests/<iid>/merge" \
    -f merge_when_pipeline_succeeds=true -f should_remove_source_branch=true
  ```
  A pipeline `skipped` by path rules (a `scripts/`- or docs-only change) leaves nothing to wait on, and the API answers `405 Method Not Allowed` — read `head_pipeline.status` from `glab api "projects/:id/merge_requests/<iid>"` before arming. On `skipped`, auto-merge means an immediate merge: ask the user, then merge with the same call minus `merge_when_pipeline_succeeds`. A later push or rebase clears it; re-arm after every push.
