---
name: implement.patch
description: "Patch for implement: move off the default branch into a fresh worktree before the first edit."
disable-model-invocation: true
user-invocable: false
---

When running `implement`, before fetching the ticket: if the current branch is the default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`), `git fetch origin` and `git worktree add <path> -b <branch> origin/<default>`, naming both per the repo's `AGENTS.md`/`CLAUDE.md`. Run the repo's worktree setup doc if it has one, then work only in the worktree; "the current branch" is its branch. Done: `git -C <path> branch --show-current` prints the new branch, and the setup steps are complete.
