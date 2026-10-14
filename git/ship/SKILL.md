---
name: ship
description: Take work through its pull request - ship (commit, push, open the pull request, optionally arm auto-merge, watch the pipeline), land (merge, delete the branch and worktree, sync the main checkout) and prune (clean merged branches and worktrees out of a repo, rebase what remains). Use when the user says ship, land or prune, push, "commit & push", "push & PR/MR", "open/create a PR/MR", "ship everything done so far", "ship and land", "land all", "merge these", asks for auto-merge or pipeline monitoring, or asks to clean up, tidy or prune branches, worktrees or the git environment.
---

Three tasks, each in its own reference. Pick them from the user's words (`/ship land`, "ship and land", "prune this repo"), read only those, and run them in order: ship, then land, then prune.

| Task | When | Reference |
|---|---|---|
| **ship** | finished work goes to a pull request ready for review; the default for a bare `/ship` | `references/ship.md` |
| **land** | merge a pull request and clean up after it, or clean up after one merged | `references/land.md` |
| **prune** | clean a whole repo: merged branches, worktrees, stray folders; rebase what stays | `references/prune.md` |

A task does not start the next one on its own: ship stops at a green pipeline for the user's review unless the ask also says land or merge; land ends by deleting the repo's other merged branches only.

Shared by all three:
- Each step ends on its own done-condition; stop and report when one cannot be met.
- The forge follows `git remote get-url origin`: github.com is GitHub (`gh`), anything else is GitLab (`glab`, where a pull request is a merge request).
- Pipelines are watched with `bash ~/.agents/skills/ship/scripts/watch-pr.sh <number>` under Monitor, never a hand-written poll. Auto-merge is armed per `references/auto-merge.md`; a branch is rebased per `references/rebase.md`.
- The harness may deny a command (a merge, a delete, a process stop). Finish every step it does not block, then hand the user the denied commands as one `!` block (Git Bash syntax) in that same message, never "the block above".
